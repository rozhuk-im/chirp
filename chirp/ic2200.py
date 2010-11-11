#!/usr/bin/python
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from chirp import chirp_common, icf, util
from chirp import bitwise

mem_format = """
struct {
  ul16  freq;
  ul16  offset;
  char name[6];
  u8   unknown1:2,
       rtone:6;
  u8   unknown2:2,
       ctone:6;
  u8   unknown3:1,
       dtcs:7;
  u8   unknown4:4,
       tuning_step:4;
  u8   unknown5[3];
  u8   unknown6:4,
       urcall:4;
  u8   r1call:4,
       r2call:4;
  u8   unknown7:1,
       digital_code:7;
  u8   is_625:1,
       unknown8:1,
       mode_am:1,
       mode_narrow:1,
       unknown9:2,
       tmode:2;
  u8   dtcs_polarity:2,
       duplex:2,
       unknown10:4;
  u8   unknown11;
  u8   mode_dv:1,
       unknown12:7;
} memory[207];

#seekto 0x1370;
struct {
  u8 unknown:2,
     empty:1,
     skip:1,
     bank:4;
} flags[207];

#seekto 0x15F0;
struct {
  char call[8];
} mycalls[6];

struct {
  char call[8];
} urcalls[6];

struct {
  char call[8];
} rptcalls[6];

"""

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+"]
DTCSP  = ["NN", "NR", "RN", "RR"]
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(6.25)

class IC2200Radio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    VENDOR = "Icom"
    MODEL = "IC-2200H"

    _model = "\x26\x98\x00\x01"
    _memsize = 6848
    _endframe = "Icom Inc\x2eD8"

    _memories = []

    _ranges = [(0x0000, 0x1340, 32),
               (0x1340, 0x1360, 16),
               (0x1360, 0x136B,  8),

               (0x1370, 0x1380, 16),
               (0x1380, 0x15E0, 32),
               (0x15E0, 0x1600, 16),
               (0x1600, 0x1640, 32),
               (0x1640, 0x1660, 16),
               (0x1660, 0x1680, 32),

               (0x16E0, 0x1860, 32),

               (0x1880, 0x1AB0, 32),

               (0x1AB8, 0x1AC0,  8),
               ]

    MYCALL_LIMIT  = (0, 6)
    URCALL_LIMIT  = (0, 6)
    RPTCALL_LIMIT = (0, 6)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 199)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def _get_special(self):
        special = { "C" : 206 }
        for i in range(0, 3):
            idA = "%iA" % (i+1)
            idB = "%iB" % (i+1)
            num = 200 + i * 2
            special[idA] = num
            special[idB] = num + 1

        return special

    def get_special_locations(self):
        return sorted(self._get_special().keys())

    def get_memory(self, number):
        if isinstance(number, str):
            number = self._get_special()[number]

        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]

        if _mem.mode_dv and not _flag.empty:
            mem = chirp_common.DVMemory()
            mem.dv_urcall   = \
                str(self._memobj.urcalls[_mem.urcall].call).rstrip()
            mem.dv_rpt1call = \
                str(self._memobj.rptcalls[_mem.r1call].call).rstrip()
            mem.dv_rpt2call = \
                str(self._memobj.rptcalls[_mem.r2call].call).rstrip()
        else:
            mem = chirp_common.Memory()

        mem.number = number
        if number < 200:
            mem.skip = _flag.skip and "S" or ""
            mem.bank = _flag.bank != 0x0A and _flag.bank or None
            if _flag.bank != 0x0A:
                mem.bank = _flag.bank
        else:
            mem.extd_number = util.get_dict_rev(self._get_special(), number)
            mem.immutable = ["number", "skip", "bank", "bank_index",
                             "extd_number"]

        if _flag.empty:
            mem.empty = True
            return mem

        mult = _mem.is_625 and 6.25 or 5.0
        mem.freq = (_mem.freq * mult) / 1000.0
        mem.offset = (_mem.offset * 5.0) / 1000.0
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = _mem.mode_dv and "DV" or _mem.mode_am and "AM" or "FM"
        if _mem.mode_narrow:
            mem.mode = "N%s" % mem.mode
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCSP[_mem.dtcs_polarity]
        mem.tuning_step = STEPS[_mem.tuning_step]
        mem.name = str(_mem.name).replace("\x0E", "").rstrip()

        return mem

    def get_memories(self, lo=0, hi=199):

        return [m for m in self._memories if m.number >= lo and m.number <= hi]

    def _wipe_memory(self, mem, char):
        self._mmap[mem.get_offset()] = char * (mem.size() / 8)

    def set_memory(self, mem):
        if isinstance(mem.number, str):
            number = self._get_special()[mem.number]
        else:
            number = mem.number

        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]

        was_empty = int(_flag.empty)

        _flag.empty = mem.empty
        if mem.empty:
            self._wipe_memory(_mem, "\xFF")
            return

        if was_empty:
            self._wipe_memory(_mem, "\x00")

        _mem.unknown8 = 0
        _mem.is_625 = chirp_common.is_fractional_step(mem.freq)
        mult = _mem.is_625 and 6.25 or 5.0
        _mem.freq = int((mem.freq * 1000) / mult)
        _mem.offset = int((mem.offset * 1000) / mult)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode_dv = mem.mode == "DV"
        _mem.mode_am = mem.mode.endswith("AM")
        _mem.mode_narrow = mem.mode.startswith("N")
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCSP.index(mem.dtcs_polarity)
        _mem.tuning_step = STEPS.index(mem.tuning_step)
        _mem.name = mem.name.ljust(6)

        if number < 200:
            _flag.skip = mem.skip != ""
            _flag.bank = mem.bank or 0x0A

        if isinstance(mem, chirp_common.DVMemory):
            urcalls = self.get_urcall_list()
            rptcalls = self.get_rptcall_list()
            _mem.urcall = urcalls.index(mem.dv_urcall.ljust(8))
            _mem.r1call = rptcalls.index(mem.dv_rpt1call.ljust(8))
            _mem.r2call = rptcalls.index(mem.dv_rpt2call.ljust(8))

    def get_raw_memory(self, number):
        size = self._memobj.memory[0].size() / 8
        offset = (number * size)
        return util.hexprint(self._mmap[offset:offset+size])

    def get_banks(self):
        banks = []

        for i in range(0, 10):
            bank = chirp_common.ImmutableBank("BANK-%s" % (chr(ord("A")+i)))
            banks.append(bank)

        return banks

    def set_banks(self, banks):
        raise errors.InvalidDataError("Bank naming not supported on this model")

    def get_urcall_list(self):
        return [str(x.call) for x in self._memobj.urcalls]

    def get_repeater_call_list(self):
        return [str(x.call) for x in self._memobj.rptcalls]

    def get_mycall_list(self):
        return [str(x.call) for x in self._memobj.mycalls]

    def set_urcall_list(self, calls):
        for i in range(*self.URCALL_LIMIT):
            self._memobj.urcalls[i].call = calls[i].ljust(8)

    def set_repeater_call_list(self, calls):
        for i in range(*self.RPTCALL_LIMIT):
            self._memobj.rptcalls[i].call = calls[i].ljust(8)

    def set_mycall_list(self, calls):
        for i in range(*self.MYCALL_LIMIT):
            self._memobj.mycalls[i].call = calls[i].ljust(8)
