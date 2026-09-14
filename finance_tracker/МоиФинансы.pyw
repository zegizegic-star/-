"""Запуск программы напрямую через Python, без сборки в exe.

Двойной клик по этому файлу открывает "Мои финансы" точно так же, как
собранный exe, но без отдельного исполняемого файла — Windows не может
заблокировать его как "неизвестное приложение", поскольку запускает
его уже установленный и доверенный интерпретатор Python (pythonw.exe),
а не наш собственный exe.

Требует: установленный Python (см. ПРОЧТИ_МЕНЯ.txt) и один раз
выполненную команду "pip install -r requirements.txt" в этой папке.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

from app import FinanceApp

if __name__ == "__main__":
    app = FinanceApp()
    app.mainloop()
