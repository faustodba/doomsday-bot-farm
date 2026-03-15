import adb
import alleanza

porta = "5555"
nome  = "FAU_02"

adb.start_server()
alleanza.raccolta_alleanza(porta, nome, print)