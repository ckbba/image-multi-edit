import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / '后端代码'))
import config
import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('app:app', host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8787')), workers=1)
