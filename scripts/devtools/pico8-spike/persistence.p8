pico-8 cartridge // http://www.pico-8.com
version 42
__lua__
-- Leaf-owned feasibility fixture. Use a disposable ROM subdirectory.
function _init()
 cartdata("leaf_pico8_spike_v1")
 previous=dget(0)
 visits=previous+1
 dset(0,visits)
 poke(0x4300,42)
 cstore(0,0x4300,1,"persistence-output.p8")
 printh("leaf spike previous="..previous.." visits="..visits)
end
function _update60()
 if btnp(4) then
  visits+=1
  dset(0,visits)
 end
end
function _draw()
 cls(1)
 print("leaf native pico-8 spike",4,8,7)
 print("previous: "..previous,4,24,7)
 print("saved: "..visits,4,34,11)
 print("o: increment saved value",4,54,7)
 print("start: native menu",4,64,7)
 print("cstore byte: 42",4,84,10)
 print("fps: "..stat(7),4,104,7)
end
