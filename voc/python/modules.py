import os

from ..java import (
    Class as JavaClass,
    Field as JavaField,
    Method as JavaMethod,
    Code as JavaCode,
    opcodes as JavaOpcodes,
    SourceFile,
    Signature,
    # LineNumberTable
)
from .blocks import Block, IgnoreBlock
from .methods import MainMethod, Method, extract_parameters
from .opcodes import ASTORE_name, ALOAD_name, IF, END_IF, DEBUG


class StaticBlock(Block):
    def tweak(self, code):
        code = [
            # Set up the globals dictionary for the module
            JavaOpcodes.NEW('java/util/Hashtable'),
            JavaOpcodes.DUP(),
            JavaOpcodes.INVOKESPECIAL('java/util/Hashtable', '<init>', '()V'),
            JavaOpcodes.PUTSTATIC(self.module.descriptor, 'globals', 'Ljava/util/Hashtable;'),

            # Load the Python builtins into the globals.
            JavaOpcodes.GETSTATIC(self.module.descriptor, 'globals', 'Ljava/util/Hashtable;'),
            JavaOpcodes.LDC('__builtins__'),
            JavaOpcodes.NEW('org/python/Object'),
            JavaOpcodes.DUP(),
            JavaOpcodes.GETSTATIC('org/Python', 'builtins', 'Ljava/util/Hashtable;'),
            JavaOpcodes.INVOKESPECIAL('org/python/Object', '<init>', '(Ljava/util/Map;)V'),
            JavaOpcodes.INVOKEVIRTUAL('java/util/Hashtable', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;'),
            JavaOpcodes.POP()
        ] + code
        return self.void_return(code)

    def store_name(self, name, arguments, allow_locals=True):
        return [
            ASTORE_name(self.localvars, '#TEMP#'),
            JavaOpcodes.GETSTATIC(self.module.descriptor, 'globals', 'Ljava/util/Hashtable;'),
            JavaOpcodes.LDC(name),
            ALOAD_name(self.localvars, '#TEMP#'),
            JavaOpcodes.INVOKEVIRTUAL('java/util/Hashtable', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;'),
            JavaOpcodes.POP(),
        ]

    def load_name(self, name, allow_locals=True):
        return [
            # look for a global var.
            JavaOpcodes.GETSTATIC(self.module.descriptor, 'globals', 'Ljava/util/Hashtable;'),
            JavaOpcodes.LDC(name),
            JavaOpcodes.INVOKEVIRTUAL('java/util/Hashtable', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;'),

            # If there's nothing in the globals, then look for a builtin.
            IF(
                [JavaOpcodes.DUP()],
                JavaOpcodes.IFNONNULL
            ),
                DEBUG('%s not found in globals' % name),
                JavaOpcodes.POP(),
                JavaOpcodes.GETSTATIC('org/Python', 'builtins', 'Ljava/util/Hashtable;'),
                JavaOpcodes.LDC(name),
                JavaOpcodes.INVOKEVIRTUAL('java/util/Hashtable', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;'),
            END_IF()
        ]

    @property
    def is_module(self):
        return True

    @property
    def descriptor(self):
        return self.parent.descriptor

    @property
    def module(self):
        return self.parent

    def add_method(self, method_name, code):
        method = Method(self.module, method_name, extract_parameters(code), static=True)
        method.extract(code)
        self.module.methods.append(method.transpile())
        return method


class Module(Block):
    def __init__(self, namespace, sourcefile):
        super().__init__()
        self.namespace = namespace
        self.sourcefile = sourcefile
        self.name = os.path.splitext(os.path.basename(sourcefile))[0]

        self.methods = []
        self.classes = []

    @property
    def descriptor(self):
        return '/'.join(self.namespace.split('.') + [self.name])

    def transpile(self):
        """Convert a Python code block into a list of Java Classfile definitions.

        Returns a list of triples:
            (namespace, class_name, javaclassfile)

        The list contains the classfile for the module, plus and classes
        defined in the module.
        """
        main_commands = []
        body_commands = []
        main_end = None

        main = None

        for cmd in self.commands:
            if main_end is not None:
                # Marker for the end of the main block:
                #   JUMP_FORWARD <main_end>
                if len(cmd.arguments) == 0 and cmd.operation.opname == 'JUMP_FORWARD' and cmd.operation.delta == main_end:
                    main_end = None

                    try:
                        main = MainMethod(self, main_commands).transpile()
                    except IgnoreBlock:
                        pass
                else:
                    main_commands.append(cmd)
            else:
                # Look for a very specific pattern, flagging the "main" method:
                #   if __name__ == '__main__':
                #       ...
                # which is represented as:
                #         LOAD_NAME: __name__
                #         LOAD_CONST: __main__
                #     COMPARE_OP: ==
                #  POP_JUMP_IF_FALSE: <end of block>
                #  ... <main code>
                #  JUMP_FORWARD <end of block>
                if (cmd.operation.opname == 'POP_JUMP_IF_FALSE'
                        and cmd.arguments[0].operation.opname == 'COMPARE_OP' and cmd.arguments[0].operation.comparison == '=='
                        and cmd.arguments[0].arguments[0].operation.opname == 'LOAD_NAME' and cmd.arguments[0].arguments[0].operation.name == '__name__'
                        and cmd.arguments[0].arguments[1].operation.opname == 'LOAD_CONST' and cmd.arguments[0].arguments[1].operation.const == '__main__'):
                    # print("Found main block")
                    if main is not None:
                        print("Found duplicate main block... replacing previous main")

                    main_end = cmd.operation.target

                # All other module-level cmds goes into the static block
                else:
                    body_commands.append(cmd)

        body = StaticBlock(self, body_commands).transpile()

        # If there is any static content, generate a classfile
        # for this module
        classfile = JavaClass(self.descriptor, supername='org/python/Object')
        classfile.attributes.append(SourceFile(os.path.basename(self.sourcefile)))

        # Add a globals dictionary to the module.
        classfile.fields.append(
            JavaField(
                'globals',
                'Ljava/util/Hashtable;',
                public=True,
                static=True,
                attributes=[
                    Signature('Ljava/util/Hashtable<Ljava/lang/String;Lorg/python/Object;>;')
                ]
            )
        )

        # Add a static method to the module.
        static_init = JavaMethod('<clinit>', '()V', public=False, static=True)
        static_init.attributes.append(body)
        classfile.methods.append(static_init)

        if main is None:
            print("Adding default main method...")
            main = JavaMethod(
                'main',
                '([Ljava/lang/String;)V',
                public=True,
                static=True,
                attributes=[
                    JavaCode(
                        max_stack=0,
                        max_locals=1,
                        code=[JavaOpcodes.RETURN()]
                    )
                ]
            )

        classfile.methods.append(main)

        # Add any static methods defined in the module
        for method in self.methods:
            classfile.methods.append(method)

        # The list of classfiles that will be returned will contain
        # at least one entry - the class for the module itself.
        classfiles = [(self.namespace, self.name, classfile)]
        # Also output any classes defined in this module.
        for class_name, classfile in self.classes:
            classfiles.append(('%s.%s' % (self.namespace, self.name), class_name, classfile))

        return classfiles
