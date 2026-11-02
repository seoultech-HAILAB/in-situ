"""Prepare ignored runtime folders; account provisioning has been retired."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def setup(port=8001):
    folder=ROOT/'.local/pilot'
    (folder/'sessions').mkdir(parents=True,exist_ok=True)
    return folder

if __name__=='__main__':
    print(setup(int(sys.argv[1]) if len(sys.argv)>1 else 8001))
