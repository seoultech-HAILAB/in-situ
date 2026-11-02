"""Compatibility entry point: no accounts or passwords are created."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.setup_team import setup

def provision():
    setup()
    print('Login has been removed. Open the server URL directly.')

if __name__=='__main__':provision()
