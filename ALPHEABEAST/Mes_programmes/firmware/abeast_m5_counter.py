#!/usr/bin/python3
import spidev
import time
import argparse
#import RPi.GPIO as gpio

## register bits
##      7          6        5        4        3     2    1    0
## reset_count cs_input cs_preamp cs_shaper gain4 int2 int1 int0
#[0, 1, 0, 1, 0, 0, 0, 0]
##
#DAC comparateurs   B8 (meme valeurs pour tous  !!)
#Sh_time            B8
#Vb_pre             C8
#Vcm                BE

spi = spidev.SpiDev()
speed = .1
spi_port_select = 0

nbmatrix = 1
matrix_id = [0, 1, 2, 3, 4, 5]

#rname = ['rst_c', 'none', 'none',
#         'none', 'bdgp', 'cs_pre', 'cs_sh', 'gx2']

rname = ['bdgp', 'cs_pre', 'cs_sh', 'gx2', 'none', 'none',
         'none', 'rst_c']
rname.reverse()

regname = ['Vpre_B', 'SH_Vcm', 'SH_TB', 'Vth_bl',
          'C_Vth0', 'C_Vth1', 'C_Vth2', 'DACMon']

countname = ['counter0', 'counter1', 'counter2']

nreg = 8
ncounter = 3
counterpos = nreg + 1
multireg = 8

b1 = [124, 194, 115, 100, 60, 130, 220]
b0 = [0, 0, 0, 0, 1, 1, 1, 1]
stdvalue = b0 * nbmatrix
bias = []
for i in range(nbmatrix):
  bias.append(b0)
  bias.append(b1)

#print(bias)


def Bit2Int(bitlist):
  out = 0
  for bit in bitlist:
    out = (out << 1) | bit
  return(out)

def Int2Bit(n):
  return [n >> i & 1 for i in range(7, -1, -1)]

def ReadFromFile(fname):
  bias = []
  f = open(fname , 'r')
  for j in range(2 * nbmatrix):
    bias.append([int(x.strip()) for x in f.readline().split(',')])
  f.close()
  return (bias)

def Write2File(bias):
  print ('write')
  f = open('abeastbias' , 'w')
  for i in bias:
    for j in range(len(i) - 1):
      f.write(str(int(i[j])) + ', ')
    f.write(str(int(i[len(i) - 1])) + '\n')
  f.close()

def spi_select_matrix(matrix) :
  spi.open(0, spi_port_select)
  spi.mode = 1
  spi.max_speed_hz = 100000
  spi.xfer([0x01 << matrix])
  spi.close()

def write_pot(input):
  msb = input >> 8
  lsb = input & 0xFF
  spi.xfer([msb, lsb])

def d_reg(matrix):
  for i in range (0, 8 + 6):
    print (chr(read_reg(i, matrix) ^ 42),)
  print

def write_reg(address, value, matrix) :
#  spi_select_matrix(matrix)
  spi.open(0, spi_port_select ^ 1)
  spi.mode = 1
  msg = [(0x80 | address), value]
  spi.xfer2(msg, 100000)
  spi.close()

#def read_reg(address, matrix) :
#  spi_select_matrix(matrix)
#  spi.open(0, spi_port_select ^ 1)
#  spi.no_cs = True
#  spi.mode = 1
#  gpio.output(25, gpio.LOW)
#  msg = [address, 0x00]
#  resp = spi.xfer2(msg, 100000)
#  gpio.output(25, gpio.HIGH)
#  spi.close()
#  return (resp[1])

def read_reg(address, matrix) :
#  spi_select_matrix(matrix)
  spi.open(0, spi_port_select ^ 1)
  spi.mode = 1
  msg = [address, 0x00]
  resp = spi.xfer2(msg, 100000)
  spi.close()
  return (resp[1])

def read_counter(matrix) :
  count = []
  read_reg(counterpos, matrix)
  for i in range(0, ncounter):
    count.append((read_reg(counterpos + ncounter * i + 2, matrix) << 16) +
                 (read_reg(counterpos + ncounter * i + 1, matrix) << 8)  +
                 (read_reg(counterpos + ncounter * i, matrix)))
  return count

def read_counter_single(i, matrix) :
#read_reg(counterpos, matrix)
  count = ((read_reg(counterpos + ncounter * i + 2, matrix) << 16) +
          (read_reg(counterpos + ncounter * i + 1, matrix) << 8)  +
          read_reg(counterpos + ncounter * i, matrix))
  return count




def check(address, value):
  write_reg(address, value)
  a = read_reg(address)
  if a == value :
    return 1
  return 0

def print_reg(matrix):
  print ('+---------------------------------------------------------+')
  print ('|        AlphaBeast            matrix : %1d                 |' % matrix)
  print ('+---------------------------------------------------------+\n|', end = "")
  print ('                     Register 8                          |\n|', end = "")
  print ('Bit  7      6      5      4      3      2      1      0  |\n+---------------------------------------------------------+\n|', end = "")
  for idx, i in enumerate(rname) :
    print ('%6s ' % i, end = "")
  print (' |\n+---------------------------------------------------------+\n|', end = "")
  for i in Int2Bit(read_reg(8, matrix)):
    print ('%6d ' % i, end = "")
  print (' |\n+---------------------------------------------------------+\n|', end = "")
  print ('Reg  0      1      2      3      4      5      6      7  |\n|', end = "")
  for i in regname :
    print ('%6s ' % i, end = "")
  print (' |\n+---------------------------------------------------------+\n|', end ="")
  for i in range (0, nreg):
    print ('%6d ' % read_reg(i, matrix), end = "")
  print (' |\n+---------------------------------------------------------+\n|', end = "")
  counter = read_counter(matrix)
  for i in countname:
    print ('%17s ' % i, end = "")
  print ('   |\n+---------------------------------------------------------+\n|', end ="")
  for i in counter:
    print ('%17d ' % i, end = "")
  print ('   |\n+---------------------------------------------------------+\n', end = "")



def set_bias(bias):
#matrix = 0
  for i, item in enumerate(bias):
    if (i % 2 == 0): # first register
      write_reg(multireg, Bit2Int(item), matrix_id[i//2])
    else :
      for k, j in enumerate(item) :
        write_reg(k, j, matrix_id[i//2])
#matrix += 1

#Write2File(bias)
#write_reg(0, 80, 0)
#write_reg(1, 255, 0)
#write_reg(7, 0xB0, 0)
#write_reg(5, 250, 0)
#write_reg(6, 20, 0)

parser = argparse.ArgumentParser()
parser.add_argument("-b", "--bias",
                    help = "read bias state from chip",
                    action = "store_true")
parser.add_argument("-w", "--write",
                    help = "set matrix register",
                    metavar = ('matrix', 'register', 'value'),
                    type = int,
                    nargs = 3)
parser.add_argument("-d", "--read",
                    help = "read matrix register",
                    metavar = ('matrix', 'register'),
                    type = int,
                    nargs = 2)
parser.add_argument("-s", "--scan",
                    help = "parameter scan, use with -s",
                    metavar = ('matrix', 'time',
                               'r5min', 'r5max', 'r5step',
                               'r6min', 'r6max', 'r6step',
                               'r7min', 'r7max', 'r7step'),
                    type = int,
                    nargs = 11,
                    default = [0, 0])
parser.add_argument("-f", "--file",
                    type = str,
                    nargs = 1,
                    help = "read and set bias from file",
                    metavar = ('filename'),
                    default = 'mypol')
parser.add_argument("-t", "--reset",
                    type = int,
                    nargs = 1,
                    metavar = ('matrix'),
                    default = 10,
                    help = "reset matrix counters")
parser.add_argument("-v", "--view",
                    type = int,
                    nargs = 1,
                    metavar = ('matrix'),
                    default = 10,
                    help = "display matrix registers")
parser.add_argument("-c", "--counter",
                    help = "read matrix single counter",
                    metavar = ('matrix', 'counter'),
                    type = int,
                    nargs = 2)


args = parser.parse_args()

#gpio.setmode(gpio.BCM)
#gpio.setup(25, gpio.OUT, initial = gpio.HIGH)


if args.file != 'mypol':
  bias = ReadFromFile(args.file[0])
  #Write2File(bias)
  set_bias(bias)
  for i in range(nbmatrix):
    print_reg(matrix_id[i])

elif args.view != 10 :
  if len(set(args.view) - set(range(0, 6))) > 0 :
    print("parameters out of range (0 - 5)")
    quit()
  else :
    print_reg(args.view[0])

elif args.reset != 10 :
  if len(set(args.reset) - set(range(0, 6))) > 0 :
    print("parameters out of range (0 - 5)")
    quit()
  else :
    print ('reset matrix %d counters' % args.reset[0])
    write_reg(multireg, read_reg(multireg, args.reset[0]) | 0x80, args.reset[0])
    write_reg(multireg, read_reg(multireg, args.reset[0]) & 0x7F, args.reset[0])
    print_reg(args.reset[0])

elif args.scan != [0, 0]:
  if len(set(args.scan[2:]) - set(range(0, 256))) > 0 :
    print ("parameters out of range (0 - 255)")
    quit()
  else :
    print ('scanning matrix', args.scan[0])
    for i in range(args.scan[2], args.scan[3] + 1, args.scan[4]):
      for j in range(args.scan[5], args.scan[6] + 1, args.scan[7]):
        for k in range(args.scan[8], args.scan[9] + 1, args.scan[10]):
          write_reg(5, i, args.scan[0])
          write_reg(6, j, args.scan[0])
          write_reg(7, k, args.scan[0])
          time.sleep(args.scan[1])
          print_reg(args.scan[0])

elif args.bias :
  for i in range(nbmatrix):
    print_reg(matrix_id[i])

elif (args.write != None):
  write_reg(args.write[1], args.write[2], args.write[0])
  print_reg(args.write[0]) 

elif (args.read != None):
  val = read_reg(args.read[1], args.read[0])
  print( 'Matrix : %d Register[%3d] = %3d' % (args.read[0], args.read[1], val))

elif (args.counter != None):
#print(args.counter)
#print(args.counter[1], args.counter[0])
  val = read_counter_single(args.counter[1], args.counter[0])
#print( 'Matrix : %d Counter[%3d] = %3d' % (args.counter[0], args.counter[1], val))
  print(val)

else :
  print("Wrong arguments use -h")


#gpio.cleanup()


quit()
