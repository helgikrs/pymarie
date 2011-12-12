# Copyright (C) 2011  Helgi Kristvin Sigurbjarnarson
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import cStringIO
import re
import struct
import sys

class HaltException(Exception):
    """Thrown on the halt opcode to stop execution"""


class MemoryOutOfBounds(Exception):
    """Thrown if someone tries to access memory out of bounds"""


class CompileError(Exception):
    """Thrown on a compile error"""


op_codes = {
        0b0000: "jns",
        0b0001: "load",
        0b0010: "store",
        0b0011: "add",
        0b0100: "subt",
        0b0101: "input",
        0b0110: "output",
        0b0111: "halt",
        0b1000: "skipcond",
        0b1001: "jump",
        0b1010: "clear",
        0b1011: "addi",
        0b1100: "jumpi",
}


op_codes_rev = dict(map(lambda (a, b): (b, a), op_codes.items()))
_reserved = set(op_codes.values() + ["dec", "hex"])


class MarieRam(object):
    """Ram object translating addresses"""
    def __init__(self, buf):
        self.ram = [0b0] * 2**9 # 1 KiB (2 bytes per word)
        n = 1
        while True:
            val = buf.read(2)
            if(val == ''):
                break
            val = struct.unpack("H", val)[0]
            self.ram[n] = val
            n += 1

    def __getitem__(self, idx):
        try:
            return self.ram[idx]
        except:
            raise MemoryOutOfBounds("Address %i does not exist." % idx)

    def __setitem__(self, idx, val):
        self.ram[idx] = val


class Marie(object):
    """Compiler / Intepreter"""
    def __init__(self, program_file):
        self._program_file = program_file
        buf = MarieCompiler(program_file).compile()
        self.me = MarieExecutor(buf)

    def run(self):
        self.me.run()


class MarieCompiler(object):
    """Marie compiler"""
    def __init__(self, fd):
        if hasattr(fd, "readline"):
            self.inp = fd
        else:
            self.inp = open(fd)

    def compile(self):
        out = cStringIO.StringIO()
        self.symbol_table = {}
        err = False
        op_c = []
        lineno = 0
        addr = 1
        for line in self.inp:
            try:
                c = self._compile_first(line, addr)
            except CompileError, e:
                err = True
                print e,
                print "at line %s" % lineno
            else:
                if c:
                    c.append(lineno)
                    op_c.append(c)
                    addr += 1

            lineno +=1

        for (addr, op, operand, lineno) in op_c:
            try:
                (addr, op, operand) = self._compile_second(addr, op, operand)
                if operand == None:
                    operand = 0
                if op != None:
                    op = (op << 12) + operand
                else:
                    op = operand
                out.write(struct.pack("H", op))
            except CompileError, e:
                err = True
                print e,
                print "at line %s" % lineno
        if err:
            sys.exit(1)
        out.seek(0)
        return out

    def _compile_first(self, line, addr):
        sre = re.compile(r" +")
        i = line.lower().strip()
        marker = None

        # comment = i[i.find('/'):0]
        if i.find('/') > -1:
            i = i[0:i.find('/')]

        if i.find(',') > -1:
            mi = i.split(',')
            marker = mi[0]
            i = mi[1]

        i = i.strip()
        op = sre.split(i)

        if marker != None:
            if marker in _reserved:
                raise CompileError("Marker %s is a reserved word" % marker)

            if marker in self.symbol_table:
                raise CompileError("Redefiniton of marker %s not allowed" % marker)

            self.symbol_table[marker] = addr

        if op[0].strip() != "":
            try:
                opcode = op_codes_rev[op[0]]
            except:
                if op[0] in ["dec", "hex"]:
                    if len(op) != 2:
                        raise CompileError("Missing number after %s" % op[0])
                    if op[0] == "dec":
                        val = int(op[1])
                    elif op[0] == "hex":
                        val = int(op[1], 16)
                    return [addr, None, val]
                else:
                    raise CompileError("Unrecognized symbol %s" % op[0])

            opr = [addr, opcode, None]

            if len(op) > 1:
                symbol = self.symbol_table.get(op[1].strip(), False)
                if symbol:
                    opr[2] = symbol
                else:
                    opr[2] = op[1].strip()
            return opr

    def _compile_second(self, addr, op, symbol):
        if not isinstance(symbol, str):
            return (addr, op, symbol)

        try:
            symbol_addr = self.symbol_table[symbol]
        except:
            # if the operation is skipcond
            if op == 0b1000:
                symbol_addr = int(symbol, 16)
            else:
                raise CompileError("Unrecognized symbol %s" % symbol)

        return (addr, op, symbol_addr)


class MarieExecutor(object):
    def __init__(self, program):
        self.m = MarieRam(program)
        # Registers
        self.ac = 0
        self.mar = 0
        self.mbr = 0
        self.pc = 0
        self.ir = 0
        self.inReg = 0
        self.outReg = 0
        #self.flagReg = None

        # program is a buffer to the compiled program
        self._program = program
        self.pc = 1

    def run(self):
        try:
            while True:
                self.fetch()
                op = self.decode()
                op()
        except (HaltException, MemoryOutOfBounds), e:
            if isinstance(e, MemoryOutOfBounds):
                print e
            print "Register values:"
            print "AC: ", self.ac
            print "MAR: ", self.mar
            print "MBR: ", self.mbr
            print "PC: ", self.pc
            print "IR: ", self.ir
            print "inREG: ", self.inReg
            print "outREG: ", self.outReg

    def fetch(self):
        self.mar = self.pc
        self.mbr = self.m[self.mar]
        self.ir = self.mbr
        self.pc += 1

    def decode(self):
        self.mar = self.ir & (1 << 12) - 1
        op = self.ir >> 12

        if hasattr(self, op_codes.get(op, -1)):
            return getattr(self, op_codes[op])
        else:
            raise NotImplementedError("Unrecognized op-code %s" % self.ir)

    def add(self):
        self.mbr = self.m[self.mar]
        self.ac += self.mbr

    def store(self):
        self.mbr = self.ac
        self.m[self.mar] = self.mbr

    def load(self):
        self.mbr = self.m[self.mar]
        self.ac = self.mbr

    def clear(self):
        self.ac = 0

    def halt(self):
        raise HaltException()

    def addi(self):
        self.mbr = self.m[self.mar]
        self.mar = self.mbr
        self.mbr = self.m[self.mar]
        self.ac += self.mbr

    def jns(self):
        self.mbr = self.pc
        self.m[self.mar] = self.mbr
        self.mbr = self.mar
        self.ac = 1 + self.mbr
        self.pc = self.ac

    def jump(self):
        self.pc = self.mar

    def jumpi(self):
        self.mbr = self.m[self.mar]
        self.pc = self.mbr

    def skipcond(self):
        instr = self.ir >> 10 & 0b11

        if instr == 0b00:
            if self.ac < 0:
                self.pc += 1
        elif instr == 0b01:
            if self.ac == 0:
                self.pc += 1
        elif instr == 0b10:
            if self.ac > 0:
                self.pc += 1

    def subt(self):
        self.mbr = self.m[self.mar]
        self.ac -= self.mbr

    def input(self):
        try:
            self.inReg = int(raw_input())
        except:
            self.inReg = ord(raw_input()[0])
        self.ac = self.inReg

    def output(self):
        self.outReg = self.ac
        try:
            asc = chr(self.outReg)
            assert asc.isalpha()
        except:
            print self.outReg
        else:
            print asc

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print "Missing file-name argument"
    else:
        mc = Marie(sys.argv[1])
        mc.run()
