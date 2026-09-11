import sys
from state_machine import JarvisMachine
from logger import setup_logger
from _tesla_proxy import start_proxy, stop_proxy



def main():
    setup_logger()
    proxy = start_proxy()
    try:
        JarvisMachine()
    finally:
        stop_proxy(proxy)

if __name__ == "__main__":
    main()