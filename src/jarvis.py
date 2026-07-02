import sys
from state_machine import JarvisMachine
from logger import setup_logger



def main():
    setup_logger()
    JarvisMachine()

if __name__ == "__main__":
    main()