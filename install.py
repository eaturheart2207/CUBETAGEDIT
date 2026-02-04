#!/usr/bin/env python3
"""
Установщик CUBEEDIT - редактора тегов музыки
Автоматически устанавливает зависимости и создаёт глобальную команду cubeedit
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def print_header():
    """Красивый заголовок"""
    logo = r"""
    _________  ____ ________________________________________    ________ 
    \_   ___ \|    |   \______   \_   _____/\__    ___/  _  \  /  _____/ 
    /    \  \/|    |   /|    |  _/|    __)_   |    | /  /_\  \/   \  ___ 
    \     \___|    |  / |    |   \|        \  |    |/    |    \    \_\  \ 
     \______  /______/  |______  /_______  /  |____|\____|__  /\______  /
            \/                 \/        \/                 \/        \/ 
    
    ═══════════════════════════════════════════════════════════════════════
                          CUBEEDIT INSTALLER
    ═══════════════════════════════════════════════════════════════════════
    """
    print(logo)


def check_python_version():
    """Проверка версии Python"""
    print("🔍 Проверка версии Python...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 6):
        print("❌ Требуется Python 3.6 или выше!")
        print(f"   Текущая версия: {sys.version}")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
    return True


def install_dependencies():
    """Установка зависимостей"""
    print("\n📦 Проверка зависимостей...")
    
    # Проверка наличия pip
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], 
                      check=True, capture_output=True)
        print("✅ pip найден")
    except subprocess.CalledProcessError:
        print("❌ pip не найден! Установите pip.")
        return False
    
    # Проверка mutagen
    print("   Проверка mutagen...")
    try:
        import mutagen
        print(f"✅ mutagen уже установлен (версия {mutagen.version_string})")
        return True
    except ImportError:
        pass
    
    # Установка mutagen
    print("   Установка mutagen...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "mutagen"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("✅ mutagen установлен")
            return True
        else:
            # Попробуем без --user
            print("   Повторная попытка без --user...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "mutagen"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("✅ mutagen установлен")
                return True
            else:
                print(f"⚠️  Предупреждение: не удалось установить mutagen автоматически")
                print(f"   Stdout: {result.stdout}")
                print(f"   Stderr: {result.stderr}")
                print("\n   Попробуйте вручную: pip install mutagen")
                
                # Проверяем, может он уже установлен в системе
                try:
                    import mutagen
                    print("✅ Но mutagen доступен в системе, продолжаем...")
                    return True
                except ImportError:
                    return False
    except Exception as e:
        print(f"❌ Ошибка при установке mutagen: {e}")
        # Всё равно проверяем
        try:
            import mutagen
            print("✅ Но mutagen доступен, продолжаем...")
            return True
        except ImportError:
            return False


def get_install_dir():
    """Определение директории установки"""
    home = Path.home()
    install_dir = home / ".local" / "bin"
    
    # Создание директории если не существует
    install_dir.mkdir(parents=True, exist_ok=True)
    
    return install_dir


def copy_files(install_dir):
    """Копирование файлов"""
    print(f"\n📂 Установка в {install_dir}...")
    
    current_dir = Path(__file__).parent
    source_file = current_dir / "tag_editor.py"
    
    if not source_file.exists():
        print(f"❌ Не найден файл: {source_file}")
        return False
    
    # Копирование основного скрипта
    dest_file = install_dir / "cubeedit"
    try:
        shutil.copy2(source_file, dest_file)
        # Сделать исполняемым
        dest_file.chmod(0o755)
        print(f"✅ Установлено: {dest_file}")
    except Exception as e:
        print(f"❌ Ошибка копирования: {e}")
        return False
    
    return True


def check_path(install_dir):
    """Проверка PATH и вывод инструкций"""
    print("\n🔧 Проверка PATH...")
    
    path_env = os.environ.get("PATH", "")
    install_dir_str = str(install_dir)
    
    if install_dir_str in path_env:
        print(f"✅ {install_dir} уже в PATH")
        return True
    else:
        print(f"⚠️  {install_dir} НЕ в PATH")
        print("\n📝 Добавьте следующую строку в ~/.bashrc или ~/.zshrc:")
        print(f"\n    export PATH=\"$PATH:{install_dir}\"\n")
        print("   Затем выполните:")
        print(f"    source ~/.bashrc")
        print("   или")
        print(f"    source ~/.zshrc")
        return False


def test_installation(install_dir):
    """Тест установки"""
    print("\n🧪 Проверка установки...")
    
    cubeedit_path = install_dir / "cubeedit"
    if cubeedit_path.exists() and os.access(cubeedit_path, os.X_OK):
        print("✅ cubeedit установлен и исполняем")
        return True
    else:
        print("❌ Проблема с правами доступа к cubeedit")
        return False


def print_usage():
    """Инструкция по использованию"""
    print("""
╔═════════════════════════════════════════════════════════════════════╗
║                    УСТАНОВКА ЗАВЕРШЕНА!                             ║
╚═════════════════════════════════════════════════════════════════════╝

📖 Использование:
    cubeedit [директория]

Примеры:
    cubeedit                    # Открыть в текущей директории
    cubeedit ~/Music            # Открыть в ~/Music
    cubeedit /path/to/music     # Открыть в указанной директории

⌨️  Горячие клавиши:
    ↑/↓        - Навигация
    Tab        - Переключение панелей
    Enter/e    - Редактировать тег
    o          - Открыть файл
    s          - Сохранить
    r          - Перезагрузить
    c/C        - Установить/удалить обложку
    h          - Помощь
    q          - Выход

🎵 Поддерживаемые форматы:
    MP3, FLAC, OGG/Vorbis/Opus, M4A/MP4, AAC, WAV, AIFF

✨ Полная поддержка русских букв и Unicode!
""")


def main():
    """Основная функция установки"""
    print_header()
    
    # Проверка Python
    if not check_python_version():
        sys.exit(1)
    
    # Установка зависимостей
    if not install_dependencies():
        print("\n❌ Установка прервана из-за ошибок с зависимостями")
        sys.exit(1)
    
    # Определение директории установки
    install_dir = get_install_dir()
    
    # Копирование файлов
    if not copy_files(install_dir):
        print("\n❌ Установка прервана из-за ошибок копирования")
        sys.exit(1)
    
    # Проверка PATH
    in_path = check_path(install_dir)
    
    # Тест установки
    if not test_installation(install_dir):
        print("\n⚠️  Установка завершена с предупреждениями")
    
    # Инструкция
    print_usage()
    
    if not in_path:
        print("\n⚠️  ВАЖНО: Не забудьте добавить ~/.local/bin в PATH!")
        print("   См. инструкции выше ↑")
    else:
        print("\n✅ Всё готово! Запустите: cubeedit")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Установка прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Непредвиденная ошибка: {e}")
        sys.exit(1)
