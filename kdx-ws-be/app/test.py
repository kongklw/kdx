from pathlib import Path
ans = Path.home()
print(ans)

BASE_DIR = Path(__file__).resolve().parent.parent
print(BASE_DIR)