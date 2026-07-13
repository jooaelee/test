#!/usr/bin/env bash
# Mac에서 Finder로 더블클릭하면 실행됩니다.
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  창고 수요예측 프로그램을 시작합니다"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[오류] Python이 설치되어 있지 않습니다."
    echo "  https://www.python.org/downloads/ 에서 설치 후 다시 실행해주세요."
    read -n 1 -s -r -p "아무 키나 누르면 창이 닫힙니다..."
    exit 1
fi

if [ ! -f ".venv/bin/python" ]; then
    echo "처음 실행이시네요. 필요한 프로그램을 준비합니다. (수 분 정도 걸릴 수 있습니다)"
    echo
    python3 -m venv .venv
    ".venv/bin/python" -m pip install --upgrade pip >/dev/null 2>&1
    ".venv/bin/python" -m pip install -r requirements.txt
    echo
    echo "준비가 완료되었습니다."
    echo
fi

echo "프로그램을 시작합니다. 잠시 후 브라우저 창이 자동으로 열립니다..."
echo "(끄시려면 이 터미널 창을 닫으세요)"
echo

".venv/bin/python" -m streamlit run app.py

read -n 1 -s -r -p "종료하려면 아무 키나 누르세요..."
