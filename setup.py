import errno
import os
import re
import subprocess
import sys
import pkg_resources
from distutils.command.build import build as _build
from distutils.command.clean import clean as _clean
from distutils.dir_util import remove_tree
from glob import glob

from setuptools import setup, Command
from setuptools.command.develop import develop as _develop
from setuptools.command.install import install as _install

import versioneer

VERSION = versioneer.get_version()

ROOT_DIR = os.path.abspath(os.path.dirname(os.path.relpath(__file__)))
JAVA_DIR = os.path.join(ROOT_DIR, 'java')
JAVA_TARGET_DIR = os.path.join(JAVA_DIR, 'target')
JAVA_PROTO_DIR = os.path.join(ROOT_DIR, "java", "src", "main", "proto")
SKEIN_JAVA_DIR = os.path.join(ROOT_DIR, 'skein', 'java')
SKEIN_JAR = os.path.join(SKEIN_JAVA_DIR, 'skein.jar')
SKEIN_PROTO_DIR = os.path.join(ROOT_DIR, 'skein', 'proto')


class build_proto(Command):
    description = "build protobuf artifacts"

    user_options = []

    def initialize_options(self):
        pass

    finalize_options = initialize_options

    def _fix_imports(self, path):
        new = ['from __future__ import absolute_import']
        with open(path) as fil:
            for line in fil:
                if re.match("^import [^ ]*_pb2 as [^ ]*$", line):
                    line = 'from . ' + line
                new.append(line)

        with open(path, 'w') as fil:
            fil.write(''.join(new))

    def run(self):
        from grpc_tools import protoc
        include = pkg_resources.resource_filename('grpc_tools', '_proto')
        for src in glob(os.path.join(JAVA_PROTO_DIR, "*.proto")):
            command = ['grpc_tools.protoc',
                       '--proto_path=%s' % JAVA_PROTO_DIR,
                       '--proto_path=%s' % include,
                       '--python_out=%s' % SKEIN_PROTO_DIR,
                       '--grpc_python_out=%s' % SKEIN_PROTO_DIR,
                       src]
            if protoc.main(command) != 0:
                self.warn('Command: `%s` failed'.format(command))
                sys.exit(1)

        for path in _compiled_protos():
            self._fix_imports(path)


class build_java(Command):
    description = "build java artifacts"

    user_options = []

    def initialize_options(self):
        pass

    finalize_options = initialize_options

    def run(self):
        # Compile the java code and copy the jar to skein/java/
        # This will be picked up as package_data later
        self.mkpath(SKEIN_JAVA_DIR)
        try:
            code = subprocess.call(['mvn', '-f', os.path.join(JAVA_DIR, 'pom.xml'),
                                    '-Dskein.version=%s' % VERSION,
                                    '--batch-mode', 'package'])
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                self.warn("Building Skein requires Maven, which wasn't found "
                          "in your environment. For information on setting "
                          "up a build environment for Skein see "
                          "https://jcristharif.com/skein/develop.html.")
                sys.exit(1)
            raise
        if code:
            sys.exit(code)

        jar_files = glob(os.path.join(JAVA_TARGET_DIR, 'skein-*.jar'))
        if not jar_files:
            self.warn('Maven compilation produced no jar files')
            sys.exit(1)
        elif len(jar_files) > 1:
            self.warn('Maven produced multiple jar files')
            sys.exit(1)

        jar = jar_files[0]

        self.copy_file(jar, SKEIN_JAR)


def _ensure_java(command):
    if not getattr(command, 'no_java', False) and not os.path.exists(SKEIN_JAR):
        command.run_command('build_java')


def _compiled_protos():
    return glob(os.path.join(SKEIN_PROTO_DIR, '*_pb2*.py'))


def _ensure_proto(command):
    if not _compiled_protos():
        command.run_command('build_proto')


class build(_build):
    def run(self):
        _ensure_java(self)
        _ensure_proto(self)
        _build.run(self)


class install(_install):
    def run(self):
        _ensure_java(self)
        _ensure_proto(self)
        _install.run(self)


class develop(_develop):
    user_options = list(_develop.user_options)
    user_options.append(('no-java', None, "Don't build the java source"))

    def initialize_options(self):
        self.no_java = False
        _develop.initialize_options(self)

    def run(self):
        if not self.uninstall:
            _ensure_java(self)
            _ensure_proto(self)
        _develop.run(self)


class clean(_clean):
    def run(self):
        if self.all:
            for d in [SKEIN_JAVA_DIR, JAVA_TARGET_DIR]:
                if os.path.exists(d):
                    remove_tree(d, dry_run=self.dry_run)
            for fil in _compiled_protos():
                if not self.dry_run:
                    os.unlink(fil)
        _clean.run(self)


is_build_step = bool({'build', 'install', 'develop',
                      'bdist_wheel'}.intersection(sys.argv))
protos_built = bool(_compiled_protos()) and 'clean' not in sys.argv

if 'build_proto' in sys.argv or (is_build_step and not protos_built):
    setup_requires = ['grpcio-tools']
else:
    setup_requires = []


install_requires = ['grpcio>=1.11.0',
                    'protobuf>=3.5.0',
                    'pyyaml',
                    'cryptography']

# Due to quirks in setuptools/distutils dependency ordering, to get the java
# and protobuf sources to build automatically in most cases, we need to check
# for them in multiple locations. This is unfortunate, but seems necessary.
cmdclass = versioneer.get_cmdclass()
cmdclass.update({'build_java': build_java,    # directly build the java source
                 'build_proto': build_proto,  # directly build the proto source
                 'build': build,              # bdist_wheel or pip install .
                 'install': install,          # python setup.py install
                 'develop': develop,          # python setup.py develop
                 'clean': clean})             # extra cleanup

# MANIFEST.in 文件，来控制文件的分发
# MANIFEST.in 需要放在和 setup.py 同级的顶级目录下，setuptools 会自动读取该文件
# 所有根目录下的以 txt 为后缀名的文件，都会分发
# 根目录下的 examples 目录 和 txt、py文件都会分发
# 路径匹配上 examples/sample?/build 不会分发
# 包名称
setup(name='skein',
      # 包版本
      version=VERSION,
      # 添加自定义命令
      cmdclass=cmdclass,
      # 维护者
      maintainer='Jim Crist-Harif',
      # 维护者的邮箱地址
      maintainer_email='jcristharif@gmail.com',
      # 程序的授权信息
      license='BSD',
      # 程序的简单描述
      description=('A simple tool and library for deploying applications on '
                   'Apache YARN'),
      # 程序的详细描述
      long_description=(open('README.rst').read()
                        if os.path.exists('README.rst') else ''),
      # 程序的官网地址
      url="https://jcristharif.com/skein/",
      project_urls={"Documentation": "https://jcristharif.com/skein/",
                    "Source": "https://github.com/jcrist/skein/",
                    "Issue Tracker": "https://github.com/jcrist/skein/issues"},
      # 程序的所属分类列表
      classifiers=[
                   # 发展时期,常见的如下
                   # 3 - Alpha
                   # 4 - Beta
                   # 5 - Production/Stable
                   "Development Status :: 5 - Production/Stable",
                   # 许可证信息
                   "License :: OSI Approved :: BSD License",
                   # 目标语言及版本
                   "Programming Language :: Java",
                   "Programming Language :: Python :: 3.5",
                   "Programming Language :: Python :: 3.6",
                   "Programming Language :: Python :: 3.7",
                   # 属于什么类型
                   "Topic :: Software Development :: Libraries :: Java Libraries",
                   "Topic :: System :: Systems Administration",
                   "Topic :: System :: Distributed Computing"],
      # 程序的关键字列表
      keywords='YARN HDFS hadoop distributed cluster',
      # 需要处理的包目录（包含__init__.py的文件夹）
      packages=['skein', 'skein.proto', 'skein.recipes'],
      # 希望被打包的文件
      package_data={'skein': ['java/*.jar']},
      # 用来支持自动生成脚本，安装后会自动生成 /usr/bin/skein 的可执行文件
      # console_scripts 指明了命令行工具的名称
      # 添加这个选项，在windows下Python目录的scripts下生成exe文件
      #
      # 该文件入口指向 skein/cli.py 的main 函数
      #     console_scripts 指明了命令行工具的名称
      #     等号前面指明了工具包的名称，等号后面的内容指明了程序的入口地址
      entry_points='''
        [console_scripts]
        skein=skein.cli:main
      ''',
      # 表明当前模块依赖哪些包，若环境中没有，则会从pypi中下载安装
      install_requires=install_requires,
      # setup.py 本身要依赖的包，这通常是为一些setuptools的插件准备的配置
      setup_requires=setup_requires,
      # python版本要求
      python_requires=">=3.5",
      # 不压缩包，而是以目录的形式安装
      zip_safe=False)
