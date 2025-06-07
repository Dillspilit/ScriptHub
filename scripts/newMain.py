import sys
import os
import json
import subprocess
import shutil
from typing import Dict, Optional, Set, List

from PyQt5.QtGui import QIcon, QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QPushButton,
    QVBoxLayout, QWidget, QTextEdit, QLabel, QHBoxLayout,
    QLineEdit, QFormLayout, QFileDialog,
    QMenu, QAction, QInputDialog, QMessageBox, QProgressBar, QListWidgetItem, QAbstractItemView
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject

from PyQt5.QtWidgets import QGraphicsOpacityEffect, QGraphicsDropShadowEffect
from PyQt5.QtCore import QPropertyAnimation, QEasingCurve

from importlib.metadata import distributions
from packaging.requirements import Requirement
import ctypes
from ctypes import wintypes
import venv

# В начале main.py
GITHUB_REPO_URL = "https://github.com/Dillspilit/ScriptHub" # Например, "https://github.com/your_user/your_scripts_repo.git"
SCRIPTS_ROOT_DIR = os.path.join("scripts")
print(SCRIPTS_ROOT_DIR)
# --- Потоки (остаются без изменений, так как они хорошо инкапсулированы) ---
# В main.py (или в отдельном файле)

class GitHubUpdaterThread(QThread):
    progress_signal = pyqtSignal(int)
    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)  # success, message

    def __init__(self, repo_url: str, local_path: str, action: str):
        super().__init__()
        self.repo_url = repo_url
        self.local_path = local_path
        self.action = action  # 'clone' или 'pull'

    def run(self):
        try:
            if self.action == 'clone':
                self.output_signal.emit(f"⚙️ Клонирую репозиторий '{self.repo_url}' в '{self.local_path}'...")
                subprocess.run(['git', 'clone', self.repo_url, self.local_path],
                               check=True, capture_output=True, text=True, encoding='utf-8')
                self.finished_signal.emit(True, "✅ Репозиторий успешно клонирован.")
            elif self.action == 'pull':
                self.output_signal.emit(f"⚙️ Обновляю репозиторий в '{self.local_path}'...")
                # Переходим в директорию репозитория
                os.chdir(self.local_path)

                # Попытка git reset --hard ORIG_HEAD в случае merge-конфликта
                # Это жестко перезапишет локальные изменения, если они есть и вызывают конфликт
                # Можно добавить более сложную логику, если нужно сохранять локальные изменения
                try:
                    subprocess.run(['git', 'pull'], check=True, capture_output=True, text=True, encoding='utf-8')
                    self.finished_signal.emit(True, "✅ Репозиторий успешно обновлен.")
                except subprocess.CalledProcessError as e:
                    if "merge conflict" in e.stderr.lower() or "local changes" in e.stderr.lower():
                        self.output_signal.emit(
                            "⚠️ Обнаружены локальные изменения или конфликт слияния. Попытка сброса...")
                        try:
                            subprocess.run(['git', 'reset', '--hard', 'HEAD'], check=True, capture_output=True,
                                           text=True, encoding='utf-8')
                            self.output_signal.emit("⚙️ Локальные изменения сброшены. Повторяю pull...")
                            subprocess.run(['git', 'pull'], check=True, capture_output=True, text=True,
                                           encoding='utf-8')
                            self.finished_signal.emit(True,
                                                      "✅ Репозиторий успешно обновлен (после сброса локальных изменений).")
                        except Exception as reset_e:
                            self.finished_signal.emit(False,
                                                      f"❌ Ошибка при сбросе локальных изменений или повторном pull: {reset_e}\n{reset_e.stderr}")
                    else:
                        self.finished_signal.emit(False, f"❌ Ошибка при обновлении репозитория: {e.stderr.strip()}")
            else:
                self.finished_signal.emit(False, "❌ Неизвестное действие Git.")
        except subprocess.CalledProcessError as e:
            self.finished_signal.emit(False, f"❌ Ошибка Git: {e.stderr.strip()}")
        except Exception as e:
            self.finished_signal.emit(False, f"❌ Непредвиденная ошибка: {str(e)}")


class GitHubManager(QObject):
    # Сигналы для MainWindow
    update_finished_signal = pyqtSignal(bool, str)  # успех, сообщение
    output_signal = pyqtSignal(str)  # для логов

    def __init__(self, script_root_dir: str, github_repo_url: str):
        super().__init__()
        self.script_root_dir = script_root_dir
        self.github_repo_url = github_repo_url
        self.repo_local_path = os.path.join(self.script_root_dir,
                                            ".github_scripts_repo")  # Скрытая папка для клонирования
        self._updater_thread: Optional[GitHubUpdaterThread] = None

    def _is_git_installed(self) -> bool:
        try:
            subprocess.run(['git', '--version'], check=True, capture_output=True, text=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def check_and_update_repository(self):
        if not self._is_git_installed():
            self.output_signal.emit("❌ Git не установлен. Автообновление невозможно.")
            self.update_finished_signal.emit(False, "Git не установлен.")
            return

        if self._updater_thread and self._updater_thread.isRunning():
            self.output_signal.emit("⚠️ Процесс обновления уже запущен. Пожалуйста, подождите.")
            return

        if not os.path.exists(self.repo_local_path):
            # Репозиторий не клонирован, клонируем
            self._updater_thread = GitHubUpdaterThread(self.github_repo_url, self.repo_local_path, 'clone')
            self._updater_thread.output_signal.connect(self.output_signal)
            self._updater_thread.finished_signal.connect(self.on_update_finished)
            self._updater_thread.start()
        else:
            # Репозиторий уже клонирован, обновляем
            self._updater_thread = GitHubUpdaterThread(self.github_repo_url, self.repo_local_path, 'pull')
            self._updater_thread.output_signal.connect(self.output_signal)
            self._updater_thread.finished_signal.connect(self.on_update_finished)
            self._updater_thread.start()

    def on_update_finished(self, success: bool, message: str):
        self.output_signal.emit(message)
        if success:
            # После успешного обновления репозитория, нужно скопировать/обновить скрипты
            self._sync_scripts_from_repo()
        self.update_finished_signal.emit(success, message)
        self._updater_thread = None  # Очищаем ссылку на поток

    def _sync_scripts_from_repo(self):
        # Эта функция будет копировать скрипты из клонированного репозитория
        # в вашу рабочую папку SCRIPTS_ROOT_DIR.
        # Это предотвратит перезапись вашей папки settings и venv.

        # Предполагаем, что ваши скрипты находятся в подпапке 'scripts/' в репозитории
        source_scripts_path = os.path.join(self.repo_local_path, "scripts")

        if not os.path.exists(source_scripts_path):
            self.output_signal.emit("❌ Не удалось найти папку 'scripts' в репозитории. Проверьте структуру.")
            return

        self.output_signal.emit("⚙️ Синхронизирую скрипты из репозитория...")
        try:
            for item_name in os.listdir(source_scripts_path):
                item_path = os.path.join(source_scripts_path, item_name)
                target_path = os.path.join(self.script_root_dir, item_name)

                if os.path.isdir(item_path):
                    # Для каждой папки скрипта
                    if item_name.startswith('.'):  # Пропускаем скрытые папки (например, .git)
                        continue

                    # Если папка скрипта уже существует, копируем содержимое, исключая .venv и settings
                    if os.path.exists(target_path):
                        self.output_signal.emit(f"   Обновляю скрипт: {item_name}")
                        for root, dirs, files in os.walk(item_path):
                            # Исключаем папки .venv и settings при копировании
                            dirs[:] = [d for d in dirs if d not in ['.venv', 'settings']]

                            relative_path = os.path.relpath(root, item_path)
                            dest_dir = os.path.join(target_path, relative_path)
                            os.makedirs(dest_dir, exist_ok=True)
                            for file in files:
                                shutil.copy2(os.path.join(root, file), os.path.join(dest_dir, file))
                    else:
                        # Если папки скрипта нет, копируем ее целиком
                        self.output_signal.emit(f"   Добавляю новый скрипт: {item_name}")
                        shutil.copytree(item_path, target_path)
            self.output_signal.emit("✅ Скрипты успешно синхронизированы.")
            # Сигнал для MainWindow обновить список скриптов
            # В MainWindow должен быть метод, который будет вызываться после этого,
            # чтобы обновить список скриптов в UI.
            # self.script_list_updated_signal.emit() # Пример, нужно определить этот сигнал в MainWindow
        except Exception as e:
            self.output_signal.emit(f"❌ Ошибка синхронизации скриптов: {str(e)}")

    def _should_auto_update(self) -> bool:
        # Здесь будет логика чтения настройки пользователя об автообновлении
        # Например, из JSON файла настроек или QSettings
        # Для примера, возвращаем True
        return True  # Замените на реальную логику


class VenvCreationThread(QThread):
    progress_signal = pyqtSignal(int)
    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, venv_path, python_path):
        super().__init__()
        self.venv_path = venv_path
        self.python_path = python_path
        self._is_running = True

    def run(self):
        try:
            self.output_signal.emit("🔍 Начинаю создание виртуального окружения...")
            self.progress_signal.emit(10)

            if not self._check_virtualenv_installed():
                self.output_signal.emit("📦 Устанавливаю virtualenv...")
                if not self._install_virtualenv():
                    self.finished_signal.emit(False, "Не удалось установить virtualenv")
                    return
                self.progress_signal.emit(30)

            self.output_signal.emit("⚙️ Создаю виртуальное окружение...")
            if not self._create_virtualenv():
                self.finished_signal.emit(False, "Ошибка создания виртуального окружения")
                return
            self.progress_signal.emit(80)

            python_exec = os.path.join(self.venv_path, "Scripts" if os.name == "nt" else "bin",
                                       "python.exe" if os.name == "nt" else "python")
            if not self._check_pip_installed(python_exec):
                self.finished_signal.emit(False, "Pip не установлен в виртуальном окружении")
                return

            self.progress_signal.emit(100)
            self.output_signal.emit("✅ Виртуальное окружение успешно создано!")
            self.finished_signal.emit(True, python_exec)

        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def _check_virtualenv_installed(self) -> bool:
        try:
            subprocess.run(
                [self.python_path, "-m", "virtualenv", "--version"],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def _install_virtualenv(self) -> bool:
        result = subprocess.run(
            [self.python_path, "-m", "pip", "install", "virtualenv"],
            capture_output=True, text=True
        )
        if result.stdout:
            self.output_signal.emit(result.stdout.strip())
        if result.stderr:
            self.output_signal.emit(f"⚠️ {result.stderr.strip()}")
        return result.returncode == 0

    def _create_virtualenv(self) -> bool:
        result = subprocess.run(
            [self.python_path, "-m", "virtualenv", self.venv_path],
            capture_output=True, text=True
        )
        if result.stdout:
            self.output_signal.emit(result.stdout.strip())
        if result.stderr:
            self.output_signal.emit(f"⚠️ {result.stderr.strip()}")
        return result.returncode == 0

    def _check_pip_installed(self, python_exec: str) -> bool:
        result = subprocess.run(
            [python_exec, "-m", "pip", "--version"],
            capture_output=True, text=True
        )
        return result.returncode == 0

    def stop(self):
        self._is_running = False


class InstallThread(QThread):
    progress_signal = pyqtSignal(int)
    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, python_exec: str, requirements_path: str):
        super().__init__()
        self.python_exec = python_exec
        self.requirements_path = requirements_path
        self._is_running = True
        self.process = None

    def run(self):
        try:
            self.output_signal.emit("🔍 Начинаю установку зависимостей...")

            self._run_command([self.python_exec, "-m", "pip", "install", "--upgrade", "pip"])

            self.output_signal.emit("📦 Устанавливаю пакеты из requirements.txt...")

            self.process = subprocess.Popen(
                [self.python_exec, "-m", "pip", "install", "-r", self.requirements_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True,
            )

            progress = 0
            for line in self._read_lines(self.process.stdout):
                if not self._is_running:
                    self.output_signal.emit("❌ Установка прервана пользователем")
                    self.process.kill()
                    self.finished_signal.emit(False)
                    return
                self.output_signal.emit(line.strip())
                progress = min(progress + 3, 95)
                self.progress_signal.emit(progress)

            for line in self._read_lines(self.process.stderr):
                self.output_signal.emit(f"⚠️ {line.strip()}")

            return_code = self.process.wait()
            if return_code == 0:
                self.progress_signal.emit(100)
                self.output_signal.emit("✅ Зависимости успешно установлены!")
                self.finished_signal.emit(True)
            else:
                self.output_signal.emit("❌ Ошибка при установке зависимостей")
                self.finished_signal.emit(False)

        except Exception as e:
            self.output_signal.emit(f"❌ Критическая ошибка при установке: {str(e)}")
            self.finished_signal.emit(False)

    def _read_lines(self, pipe):
        try:
            for line in iter(pipe.readline, ''):
                yield line
        finally:
            pipe.close()

    def _run_command(self, cmd: List[str]) -> bool:
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if process.stdout:
            self.output_signal.emit(process.stdout.strip())
        if process.stderr:
            self.output_signal.emit(f"⚠️ {process.stderr.strip()}")
        return process.returncode == 0

    def stop(self):
        self._is_running = False
        if self.process and self.process.poll() is None:
            self.process.kill()


class ScriptOperations(QObject):  # Наследуем от QObject, если будут сигналы/слоты
    """Handles file system operations for scripts."""
    # Вместо прямого вызова log_output, будем использовать сигнал или колбэк
    log_output_signal = pyqtSignal(str)
    script_deleted_signal = pyqtSignal(str)  # Новый сигнал при удалении скрипта
    script_renamed_signal = pyqtSignal(str, str)  # Новый сигнал при переименовании скрипта

    def __init__(self):
        super().__init__()
        # log_output_callback больше не нужен здесь напрямую, используем сигнал
        pass

    def add_script_file(self, source_path: str) -> Optional[str]:
        filename = os.path.basename(source_path)
        name_no_ext = os.path.splitext(filename)[0]
        script_dir = os.path.join("scripts", name_no_ext)
        script_path = os.path.join(script_dir, "script.py")

        if os.path.exists(script_dir):
            self.log_output_signal.emit(f"⚠️ Скрипт {filename} уже существует.")
            return None

        os.makedirs(script_dir, exist_ok=True)
        shutil.copy(source_path, script_path)
        self.log_output_signal.emit(f"✅ Скрипт {filename} успешно добавлен!")
        return name_no_ext

    def delete_script_folder(self, script_name: str) -> bool:
        script_dir = os.path.join("scripts", script_name)
        if os.path.exists(script_dir):
            shutil.rmtree(script_dir)
            self.log_output_signal.emit(f"🗑️ Скрипт {script_name} успешно удален.")
            self.script_deleted_signal.emit(script_name)  # Отправляем сигнал
            return True
        return False

    def rename_script_folder(self, old_name: str, new_name: str) -> bool:
        old_script_dir = os.path.join("scripts", old_name)
        new_script_dir = os.path.join("scripts", new_name)

        if os.path.exists(new_script_dir):
            self.log_output_signal.emit(f"⚠️ Скрипт с именем '{new_name}' уже существует.")
            return False
        if not os.path.exists(old_script_dir):
            self.log_output_signal.emit(f"❌ Скрипт '{old_name}' не найден.")
            return False

        os.rename(old_script_dir, new_script_dir)
        self.log_output_signal.emit(f"✏️ Скрипт '{old_name}' переименован в '{new_name}'.")
        self.script_renamed_signal.emit(old_name, new_name)  # Отправляем сигнал
        return True

    def get_script_path(self, script_name: str) -> Optional[str]:
        script_dir = os.path.join("scripts", script_name)
        script_path = os.path.join(script_dir, "script.py")
        return script_path if os.path.exists(script_path) else None

    def get_script_dir(self, script_name: str) -> str:
        return os.path.join("scripts", script_name)


class DependencyManagement(QObject):  # Наследуем от QObject
    """Manages Python dependencies and virtual environments for scripts."""
    # Теперь сигналы для DependencyManagement, а не колбэки
    log_output_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    venv_created_signal = pyqtSignal(str, str)  # script_dir, python_exec_path
    dependencies_installed_signal = pyqtSignal(str, bool)  # script_dir, success

    def __init__(self):
        super().__init__()
        self._installed_packages_cache: Optional[Dict[str, str]] = None
        self._install_thread: Optional[InstallThread] = None
        self._venv_thread: Optional[VenvCreationThread] = None

    def _get_stdlib_list(self) -> Set[str]:
        return {
            'os', 'sys', 'json', 'time', 'datetime', 're', 'math', 'random',
            'subprocess', 'shutil', 'ctypes', 'wintypes', 'collections',
            'logging', 'threading', 'multiprocessing', 'queue', 'urllib',
            'ssl', 'socket', 'hashlib', 'itertools', 'functools', 'operator',
            'pathlib', 'tempfile', 'pickle', 'copy', 'weakref', 'enum',
            'numbers', 'statistics', 'typing', 'struct', 'binascii',
            'heapq', 'bisect', 'array', 'sched', 'locale', 'unicodedata',
            'string', 'textwrap', 'difflib', 'csv', 'configparser', 'glob',
            'fnmatch', 'linecache', 'shlex', 'zipfile', 'tarfile', 'zlib',
            'gzip', 'bz2', 'lzma', 'zipimport', 'importlib', 'pkgutil',
            'modulefinder', 'runpy', 'traceback', 'inspect', 'ast', 'symtable',
            'tokenize', 'keyword', 'token', 'opcode', 'dis', 'pickletools',
            'code', 'codeop', 'pprint', 'reprlib', 'weakref', 'abc', 'collections',
            'contextlib', 'functools', 'itertools', 'operator', 'types', 'typing',
            'copyreg', 'marshal', 'warnings', 'errno', 'io', 'selectors',
            'threading', 'multiprocessing', 'concurrent', 'asyncio', 'socket',
            'ssl', 'signal', 'mmap', 'fcntl', 'pwd', 'grp', 'posix', 'nt',
            'spwd', 'crypt', 'termios', 'tty', 'pty', 'resource', 'syslog',
            'pipes', 'select', 'asyncore', 'asynchat', 'email', 'json', 'mailbox',
            'mimetypes', 'base64', 'binhex', 'binascii', 'quopri', 'uu',
            'html', 'xml', 'webbrowser', 'cgi', 'cgitb', 'wsgiref', 'urllib',
            'ftplib', 'poplib', 'imaplib', 'nntplib', 'smtplib', 'smtpd',
            'telnetlib', 'uuid', 'socketserver', 'http', 'http.server',
            'http.client', 'ftplib', 'poplib', 'imaplib', 'nntplib',
            'smtplib', 'smtpd', 'telnetlib', 'xmlrpc', 'ipaddress',
            'audioop', 'aifc', 'sunau', 'wave', 'chunk', 'colorsys',
            'imghdr', 'sndhdr', 'ossaudiodev', 'getopt', 'argparse',
            'getpass', 'curses', 'platform', 'errno', 'ctypes', 'threading',
            'zipimport', 'pkgutil', 'modulefinder', 'runpy', 'importlib',
            'imp', 'parser', 'ast', 'symtable', 'symbol', 'token', 'keyword',
            'tokenize', 'tabnanny', 'pyclbr', 'py_compile', 'compileall',
            'dis', 'pickletools', 'formatter', 'msilib', 'msvcrt', 'winreg',
            'winsound', 'posix', 'pwd', 'spwd', 'grp', 'crypt', 'termios',
            'tty', 'pty', 'fcntl', 'pipes', 'resource', 'nis', 'syslog',
            'optparse', 'imp', 'importlib', 'ensurepip', 'venv', 'zipapp'
        }

    def analyze_imports(self, script_path: str) -> Optional[List[str]]:
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                content = f.read()

            stdlib = self._get_stdlib_list()
            imports = set()
            lines = [line.strip() for line in content.split('\n')
                     if line.strip() and not line.strip().startswith('#')]

            for line in lines:
                if line.startswith('import '):
                    modules = [m.strip().split('.')[0].split(' as ')[0]
                               for m in line[7:].split(',')]
                    imports.update(m for m in modules if m and m not in stdlib)
                elif line.startswith('from '):
                    parts = line.split()
                    if len(parts) >= 4 and parts[2] == 'import':
                        module = parts[1].split('.')[0]
                        if module not in stdlib:
                            imports.add(module)
            return sorted(imports) if imports else None
        except Exception as e:
            self.log_output_signal.emit(f"⚠️ Ошибка анализа скрипта: {str(e)}")
            return None

    def create_requirements_file(self, script_dir: str, imports: List[str]):
        requirements_path = os.path.join(script_dir, "requirements.txt")
        with open(requirements_path, 'w', encoding='utf-8') as f:  # Added encoding here
            f.write("\n".join(imports) + "\n")
        self.log_output_signal.emit(f"✅ Создан requirements.txt для {os.path.basename(script_dir)}")

    def check_dependencies(self, script_dir: str) -> bool:
        requirements_path = os.path.join(script_dir, "requirements.txt")
        if not os.path.exists(requirements_path):
            self.log_output_signal.emit("ℹ️ requirements.txt не найден, зависимости не требуются.")
            return True

        try:
            # self.log_output_signal.emit("🔍 Проверяю зависимости...")
            missing = []
            installed = self.get_installed_packages()

            with open(requirements_path, 'r', encoding='utf-8') as f:
                requirements = [line.strip() for line in f
                                if line.strip() and not line.strip().startswith('#')]

            for req_str in requirements:
                try:
                    req = Requirement(req_str)
                    pkg_name = req.name.lower()

                    if pkg_name not in installed:
                        missing.append(str(req))
                    elif req.specifier and not req.specifier.contains(installed[pkg_name]):
                        missing.append(f"{pkg_name} (требуется {req.specifier}, установлено {installed[pkg_name]})")
                except Exception as e:
                    self.log_output_signal.emit(f"⚠️ Ошибка разбора строки '{req_str}': {e}")
                    continue

            if missing:
                msg = "⚠️ Обнаружены проблемы с зависимостями:\n" + "\n".join(missing)
                self.log_output_signal.emit(msg)
                return False
            self.log_output_signal.emit("✅ Все зависимости удовлетворяют требованиям.")
            return True
        except Exception as e:
            self.log_output_signal.emit(f"❌ Ошибка проверки зависимостей: {str(e)}")
            return False

    def _on_venv_creation_finished(self, script_dir: str, success: bool, result: str):
        if success:
            self.log_output_signal.emit("✅ Виртуальное окружение успешно создано!")
            self.venv_created_signal.emit(script_dir, result)  # Отправляем сигнал, ЧТО Venv готово
        else:
            self.log_output_signal.emit(f"❌ Ошибка создания виртуального окружения: {result}")
        self.progress_signal.emit(0)

    # Метод create_or_get_venv останется почти таким же:
    def create_or_get_venv(self, script_dir: str) -> Optional[str]:
        venv_dir = os.path.join(script_dir, ".venv")
        scripts_dir = os.path.join(venv_dir, "Scripts" if os.name == "nt" else "bin")
        python_exec = os.path.join(scripts_dir, "python.exe" if os.name == "nt" else "python")

        if os.path.exists(python_exec):
            self.log_output_signal.emit(f"✅ Виртуальное окружение найдено: {python_exec}")
            # Если Venv уже есть, просто возвращаем путь
            return python_exec

        # Если Venv нет, запускаем поток создания и НЕ возвращаем путь сразу.
        # Путь будет передан через сигнал venv_created_signal после завершения потока.
        if self._venv_thread and self._venv_thread.isRunning():
            self.log_output_signal.emit("⚠️ Создание виртуального окружения уже запущено. Ожидайте.")
            return None

        self.log_output_signal.emit("⚙️ Создаю виртуальное окружение...")
        self._venv_thread = VenvCreationThread(venv_dir, sys.executable)
        self._venv_thread.output_signal.connect(self.log_output_signal.emit)
        self._venv_thread.progress_signal.connect(self.progress_signal.emit)
        self._venv_thread.finished_signal.connect(
            lambda success, exec_path: self._on_venv_creation_finished(script_dir, success, exec_path)
        )
        self._venv_thread.start()
        return None  # Важно: возвращаем None, пока Venv не будет готово




    def install_dependencies(self, script_dir: str, python_exec: str):
        requirements_path = os.path.join(script_dir, "requirements.txt")
        if not os.path.exists(requirements_path):
            self.log_output_signal.emit("ℹ️ requirements.txt не найден для установки.")
            self.progress_signal.emit(0)
            self.dependencies_installed_signal.emit(script_dir, True)  # Если нет reqs, считаем успех
            return

        if self._install_thread and self._install_thread.isRunning():
            self.log_output_signal.emit("⚠️ Установка зависимостей уже запущена. Ожидайте.")
            return

        self.log_output_signal.emit(f"📦 Запускаю установку зависимостей для {os.path.basename(script_dir)}...")
        self._install_thread = InstallThread(python_exec, requirements_path)
        self._install_thread.output_signal.connect(self.log_output_signal.emit)
        self._install_thread.progress_signal.connect(self.progress_signal.emit)
        self._install_thread.finished_signal.connect(
            lambda success: self._on_install_finished(script_dir, success)
        )
        self._install_thread.start()

    def _on_install_finished(self, script_dir: str, success: bool):
        if success:
            self.log_output_signal.emit("✅ Установка зависимостей завершена успешно.")
        else:
            self.log_output_signal.emit("❌ Установка зависимостей завершена с ошибками.")
        self.clear_packages_cache()
        self.progress_signal.emit(0)
        self.dependencies_installed_signal.emit(script_dir, success)  # Отправляем сигнал

    def get_installed_packages(self) -> Dict[str, str]:
        if self._installed_packages_cache is None:
            self._installed_packages_cache = {
                dist.metadata["Name"].lower(): dist.version
                for dist in distributions()
            }
        return self._installed_packages_cache

    def clear_packages_cache(self):
        self._installed_packages_cache = None


class SettingsManager(QObject):  # Наследуем от QObject
    """Manages script-specific settings files."""
    log_output_signal = pyqtSignal(str)  # Сигнал для логирования

    def __init__(self):
        super().__init__()

    def get_settings_path(self, script_name: str) -> str:
        script_dir = os.path.join("scripts", script_name)
        return os.path.join(script_dir, "settings.json")

    def load_settings(self, settings_path: str) -> Optional[Dict[str, str]]:
        if not os.path.exists(settings_path):
            return None
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.log_output_signal.emit(f"❌ Ошибка загрузки настроек из {os.path.basename(settings_path)}: {str(e)}")
            return None

    def save_settings(self, settings_path: str, data: Dict[str, str]):
        try:
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            with open(settings_path, "w", encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            self.log_output_signal.emit(f"✅ Настройки сохранены в {os.path.basename(settings_path)}")
        except Exception as e:
            self.log_output_signal.emit(f"❌ Ошибка сохранения настроек в {os.path.basename(settings_path)}: {str(e)}")

    def copy_settings_file(self, source_path: str, destination_path: str) -> bool:
        try:
            with open(source_path, "r", encoding='utf-8') as f:  # Added encoding here
                json.load(f)
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            shutil.copy(source_path, destination_path)
            self.log_output_signal.emit(f"✅ Файл настроек {os.path.basename(source_path)} успешно скопирован.")
            return True
        except json.JSONDecodeError:
            self.log_output_signal.emit(
                f"❌ Выбранный файл '{os.path.basename(source_path)}' не является валидным JSON.")
            return False
        except Exception as e:
            self.log_output_signal.emit(f"❌ Ошибка копирования файла настроек: {str(e)}")
            return False


class ScriptListManager(QObject):  # Наследуем от QObject
    """Manages the list of scripts and their pinning state."""
    log_output_signal = pyqtSignal(str)  # Сигнал для логирования

    def __init__(self):
        super().__init__()
        self.pinned_scripts = set()
        self.load_pinned_scripts()

    def load_pinned_scripts(self):
        try:
            with open('pinned_scripts.json', 'r', encoding='utf-8') as f:
                self.pinned_scripts = set(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            self.pinned_scripts = set()
            self.log_output_signal.emit("ℹ️ Файл закрепленных скриптов не найден или пуст.")

    def save_pinned_scripts(self):
        try:
            with open('pinned_scripts.json', 'w', encoding='utf-8') as f:
                json.dump(list(self.pinned_scripts), f)
        except Exception as e:
            self.log_output_signal.emit(f"❌ Ошибка сохранения закрепленных скриптов: {e}")

    def get_all_scripts(self) -> List[str]:
        script_dir = os.path.join(os.getcwd(), "scripts")
        os.makedirs(script_dir, exist_ok=True)

        all_scripts = []
        for folder in os.listdir(script_dir):
            folder_path = os.path.join(script_dir, folder)
            script_file = os.path.join(folder_path, "script.py")
            if os.path.isdir(folder_path) and os.path.isfile(script_file):
                all_scripts.append(folder)

        pinned_ordered = []
        for script in self.get_saved_script_order():
            if script in self.pinned_scripts and script in all_scripts:
                pinned_ordered.append(script)

        other_scripts = sorted([s for s in all_scripts if s not in self.pinned_scripts])

        return pinned_ordered + other_scripts

    def toggle_pin_script(self, script_name: str):
        if script_name in self.pinned_scripts:
            self.pinned_scripts.remove(script_name)
            self.log_output_signal.emit(f"📌 Скрипт '{script_name}' откреплен.")
        else:
            self.pinned_scripts.add(script_name)
            self.log_output_signal.emit(f"📌 Скрипт '{script_name}' закреплен.")
        self.save_pinned_scripts()

    def save_scripts_order(self, script_order: List[str]):
        try:
            with open('scripts_order.json', 'w', encoding='utf-8') as f:
                json.dump(script_order, f)
        except Exception as e:
            self.log_output_signal.emit(f"❌ Ошибка сохранения порядка скриптов: {e}")

    def get_saved_script_order(self) -> List[str]:
        try:
            with open('scripts_order.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []


class ScriptExecutor(QObject):  # Наследуем от QObject
    """Manages the execution and stopping of Python scripts."""
    script_started_signal = pyqtSignal(str)  # Передаем имя скрипта
    script_finished_signal = pyqtSignal(str)  # Передаем имя скрипта
    output_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self):  # log_output_callback больше не нужен
        super().__init__()
        self.worker_thread: Optional[WorkerThread] = None

    def run_script(self, script_path: str, script_dir: str, python_exec: str, script_name: str):
        if self.worker_thread and self.worker_thread.isRunning():
            self.output_signal.emit("⚠️ Скрипт уже запущен, остановите его перед запуском нового.")
            return

        self.output_signal.emit(f"▶ Запускаю скрипт: {script_name}")
        self.worker_thread = WorkerThread(script_path, cwd=script_dir, python_exec=python_exec)
        self.worker_thread.output_signal.connect(self.output_signal.emit)
        self.worker_thread.error_signal.connect(self.error_signal.emit)
        self.worker_thread.finished_signal.connect(lambda: self._on_script_finished(script_name))
        self.worker_thread.start()
        self.script_started_signal.emit(script_name)

    def stop_script(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.output_signal.emit("⏹ Останавливаю скрипт...")
            self.worker_thread.stop()
        else:
            self.output_signal.emit("ℹ️ Нет запущенных скриптов для остановки.")

    def _on_script_finished(self, script_name: str):
        self.output_signal.emit("✅ Выполнение скрипта завершено.")
        self.script_finished_signal.emit(script_name)
        self.worker_thread = None


class WorkerThread(QThread):
    output_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, script_path: str, cwd: Optional[str] = None, python_exec: str = sys.executable):
        super().__init__()
        self.script_path = os.path.abspath(script_path)
        self.cwd = os.path.abspath(cwd) if cwd else None
        self.python_exec = python_exec
        self.process = None
        self._is_running = True

    def run(self):
        try:
            if not os.path.exists(self.script_path):
                self.error_signal.emit(f"Ошибка: файл скрипта не найден: {self.script_path}")
                return

            self.process = subprocess.Popen(
                [self.python_exec, self.script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                cwd=self.cwd
            )

            while self._is_running and self.process.poll() is None:
                output = self.process.stdout.readline()
                if output:
                    self.output_signal.emit(output.strip())

            if not self._is_running:
                return

            _, stderr = self.process.communicate()
            if stderr:
                self.error_signal.emit(stderr.strip())

        except Exception as e:
            self.error_signal.emit(f"❌ Критическая ошибка выполнения: {str(e)}")
        finally:
            self.finished_signal.emit()

    def stop(self):
        self._is_running = False
        if self.process:
            self.process.terminate()
            if self.process.poll() is None:
                QThread.msleep(100)
                if self.process.poll() is None:
                    self.process.kill()
            self.process.wait()


class StylesheetHelper:
    @staticmethod
    def add_shadow(widget):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 100))
        widget.setGraphicsEffect(shadow)

    @staticmethod
    def animate_button_click(button):
        def start_animation():
            effect = QGraphicsOpacityEffect(button)
            button.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity")
            animation.setDuration(250)
            animation.setStartValue(0.5)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.InOutQuad)
            animation.start(QPropertyAnimation.DeleteWhenStopped)
            button.animation = animation

        try:
            button.clicked.disconnect(button.animation_slot)
            del button.animation_slot
        except (AttributeError, TypeError):
            pass

        button.animation_slot = start_animation
        button.clicked.connect(button.animation_slot)


class ScriptManager(QWidget):
    """Manages the list of scripts and their interactions."""
    # Сигналы, которые ScriptManager отправляет в MainWindow
    script_selected_signal = pyqtSignal(str)  # Отправляем имя выбранного скрипта
    request_add_script_signal = pyqtSignal(str)  # Отправляем путь к новому скрипту
    request_delete_script_signal = pyqtSignal(str)  # Отправляем имя скрипта для удаления
    request_rename_script_signal = pyqtSignal(str, str)  # Отправляем старое и новое имя
    request_change_settings_file_signal = pyqtSignal(str)  # Отправляем имя скрипта для смены настроек
    request_run_script_signal = pyqtSignal(str)  # Отправляем имя скрипта для запуска
    request_stop_script_signal = pyqtSignal()  # Сигнал для остановки текущего скрипта
    log_output_signal = pyqtSignal(str)  # Для внутренних логов ScriptManager, если есть
    scripts_loaded_signal = pyqtSignal()  # Добавьте этот сигнал

    def __init__(self):
        super().__init__()
        self.script_operations = ScriptOperations()
        self.script_list_manager = ScriptListManager()
        self._init_ui()
        self.load_scripts_to_ui()

        # Соединяем сигналы ScriptOperations с нашими собственными сигналами
        self.script_operations.log_output_signal.connect(self.log_output_signal.emit)
        self.script_operations.script_deleted_signal.connect(self._on_script_deleted_internal)
        self.script_operations.script_renamed_signal.connect(self._on_script_renamed_internal)

        self.script_list_manager.log_output_signal.connect(self.log_output_signal.emit)

    def _init_ui(self):
        self.setAcceptDrops(True)

        self.script_list = QListWidget()
        self.script_list.setFocusPolicy(Qt.NoFocus)
        self.script_list.currentItemChanged.connect(self._on_script_selection_changed)
        self.script_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.script_list.customContextMenuRequested.connect(self._open_context_menu)

        self.script_list.setDragEnabled(True)
        self.script_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.script_list.setDefaultDropAction(Qt.MoveAction)
        self.script_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.script_list.model().rowsMoved.connect(self._on_scripts_reordered)

        self.script_list.setAcceptDrops(True)
        self.script_list.viewport().setAcceptDrops(True)

        self.run_button = QPushButton("▶ Запустить")
        StylesheetHelper.animate_button_click(self.run_button)
        self.run_button.clicked.connect(self._on_run_button_clicked)

        self.stop_button = QPushButton("⏹ Остановить")
        self.stop_button.setEnabled(False)
        StylesheetHelper.animate_button_click(self.stop_button)
        self.stop_button.clicked.connect(self.request_stop_script_signal.emit)

        add_script_btn = QPushButton("+ Добавить скрипт")
        add_script_btn.clicked.connect(self._on_add_script_button_clicked)
        StylesheetHelper.animate_button_click(add_script_btn)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("📜 Скрипты"))
        layout.addWidget(add_script_btn)
        layout.addWidget(self.script_list)
        layout.addWidget(self.run_button)
        layout.addWidget(self.stop_button)
        self.setLayout(layout)

        StylesheetHelper.add_shadow(self.script_list)
        StylesheetHelper.add_shadow(self.run_button)
        StylesheetHelper.add_shadow(self.stop_button)
        StylesheetHelper.add_shadow(add_script_btn)


    def _on_run_button_clicked(self):
        selected_script_name = self.get_selected_script_name()
        if selected_script_name:
            # Отправляем сигнал на запуск скрипта в MainWindow, который будет управлять логикой запуска
            self.request_run_script_signal.emit(selected_script_name)

    def _on_add_script_button_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите скрипт", "", "Python (*.py)")
        if path:
            # Отправляем сигнал на добавление скрипта в MainWindow
            self.request_add_script_signal.emit(path)

    def set_run_stop_button_states(self, running: bool):
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if all(url.toLocalFile().lower().endswith('.py') for url in event.mimeData().urls()):
                event.acceptProposedAction()
                self.script_list.setStyleSheet("""
                    QListWidget {
                        border: 2px dashed #4CAF50;
                        background-color: rgba(76, 175, 80, 0.1);
                    }
                """)
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.script_list.setStyleSheet("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.script_list.setStyleSheet("")
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith('.py'):
                    # Отправляем сигнал на добавление скрипта в MainWindow
                    self.request_add_script_signal.emit(file_path)
            event.acceptProposedAction()
        else:
            event.ignore()

    # ВНУТРЕННИЕ МЕТОДЫ ScriptManager для реакции на сигналы от ScriptOperations
    def _on_script_deleted_internal(self, script_name: str):
        self.script_list_manager.load_pinned_scripts()
        self.load_scripts_to_ui()
        self.script_selected_signal.emit("")  # Отменяем выбор

    def _on_script_renamed_internal(self, old_name: str, new_name: str):
        if old_name in self.script_list_manager.pinned_scripts:
            self.script_list_manager.pinned_scripts.remove(old_name)
            self.script_list_manager.pinned_scripts.add(new_name)
            self.script_list_manager.save_pinned_scripts()
        self.load_scripts_to_ui()
        self.script_selected_signal.emit(new_name)

    def load_scripts_to_ui(self):
        self.script_list.clear()
        all_scripts = self.script_list_manager.get_all_scripts()
        for script_name in all_scripts:
            item = QListWidgetItem(script_name)
            if script_name in self.script_list_manager.pinned_scripts:
                item.setData(Qt.UserRole + 1, True)
                item.setIcon(QIcon.fromTheme("pin"))
                item.setBackground(QColor(40, 40, 60))
                item.setForeground(QColor(200, 200, 255))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            self.script_list.addItem(item)
        if self.script_list.count() > 0:
            # После обновления списка, если был выбран скрипт, выбираем его снова
            # Иначе, выбираем первый
            current_selected = self.get_selected_script_name()
            if current_selected and current_selected in all_scripts:
                # Найти и выбрать элемент с тем же именем
                items = self.script_list.findItems(current_selected, Qt.MatchExactly)
                if items:
                    self.script_list.setCurrentItem(items[0])
            elif self.script_list.count() > 0:
                self.script_list.setCurrentRow(0)
            else:  # Если скриптов нет
                self.script_selected_signal.emit("")
        self.scripts_loaded_signal.emit()  # Вызываем после загрузки

    def get_selected_script_name(self) -> Optional[str]:
        item = self.script_list.currentItem()
        return item.text() if item else None

    def _on_script_selection_changed(self):
        script_name = self.get_selected_script_name()
        if script_name:
            self.script_selected_signal.emit(script_name)

    def _on_scripts_reordered(self, parent, start, end, destination, row):
        current_order = [self.script_list.item(i).text() for i in range(self.script_list.count())]
        self.script_list_manager.save_scripts_order(current_order)

    def _open_context_menu(self, position):
        item = self.script_list.itemAt(position)
        if not item:
            return

        script_name = item.text()
        menu = QMenu()

        pin_action_text = "📌 Открепить" if script_name in self.script_list_manager.pinned_scripts else "📌 Закрепить"
        pin_action = QAction(pin_action_text, self)
        pin_action.triggered.connect(lambda: self._toggle_pin_script_ui(script_name))

        delete_action = QAction("🗑 Удалить скрипт", self)
        # Отправляем сигнал в MainWindow для обработки удаления
        delete_action.triggered.connect(lambda: self.request_delete_script_signal.emit(script_name))

        rename_action = QAction("✏️ Переименовать скрипт", self)
        # Отправляем сигнал в MainWindow для обработки переименования
        rename_action.triggered.connect(lambda: self._request_rename_script(script_name))

        change_settings_action = QAction("📂 Заменить файл настроек", self)
        # Отправляем сигнал в MainWindow для обработки смены файла настроек
        change_settings_action.triggered.connect(lambda: self.request_change_settings_file_signal.emit(script_name))

        menu.addAction(pin_action)
        menu.addSeparator()
        menu.addAction(rename_action)
        menu.addAction(change_settings_action)
        menu.addSeparator()
        menu.addAction(delete_action)

        menu.exec_(self.script_list.mapToGlobal(position))

    def _toggle_pin_script_ui(self, script_name: str):
        self.script_list_manager.toggle_pin_script(script_name)
        self.load_scripts_to_ui()

    def _request_rename_script(self, script_name: str):
        new_name, ok = QInputDialog.getText(self, "Переименовать скрипт", "Введите новое имя для скрипта:",
                                            QLineEdit.Normal, script_name)
        if ok and new_name and new_name != script_name:
            self.request_rename_script_signal.emit(script_name, new_name)


class SettingsPanel(QWidget):
    """UI for displaying and editing script settings."""
    # SettingsPanel тоже должен иметь свой собственный log_output_signal
    log_output_signal = pyqtSignal(str)
    request_copy_settings_file_signal = pyqtSignal(str, str)  # source_path, dest_path

    def __init__(self):
        super().__init__()
        self.settings_manager = SettingsManager()  # Теперь SettingsManager сам отправляет логи
        self.fields: Dict[str, QLineEdit] = {}
        self.current_script_name: Optional[str] = None
        self.current_settings_path: Optional[str] = None
        self.load_btn = None
        self._init_ui()

        # Соединяем сигналы SettingsManager с нашим собственным сигналом
        self.settings_manager.log_output_signal.connect(self.log_output_signal.emit)

    def _init_ui(self):
        self.setAcceptDrops(True)
        self.form = QFormLayout()
        self.setLayout(self.form)
        StylesheetHelper.add_shadow(self)

    def dragEnterEvent(self, event):
        if (event.mimeData().hasUrls() and self.current_script_name and
                len(event.mimeData().urls()) == 1 and
                event.mimeData().urls()[0].toLocalFile().lower().endswith('.json')):
            event.acceptProposedAction()
            self.setStyleSheet("""
                QWidget {
                    border: 2px dashed #2196F3;
                    background-color: rgba(33, 150, 243, 0.1);
                }
            """)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setStyleSheet("")
        if (event.mimeData().hasUrls() and self.current_script_name and
                len(event.mimeData().urls()) == 1):
            file_path = event.mimeData().urls()[0].toLocalFile()
            if file_path.lower().endswith('.json'):
                # Отправляем сигнал в MainWindow для обработки копирования
                self.request_copy_settings_file_signal.emit(file_path, self.current_settings_path)
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def load_settings_for_script(self, script_name: str):
        self._clear_form()
        self.current_script_name = script_name
        if not script_name:
            self.current_settings_path = None
            return

        self.current_settings_path = self.settings_manager.get_settings_path(script_name)

        if not os.path.exists(self.current_settings_path):
            self._show_no_settings_warning()
        else:
            self._load_json_into_form()

    def _clear_form(self):
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.fields = {}

    def _show_no_settings_warning(self):
        warning = QLabel("⚠️ У этого скрипта ещё нет файла настроек.\n\nПеретащите .json файл сюда или нажмите кнопку.")
        warning.setAlignment(Qt.AlignCenter)
        warning.setStyleSheet("""
            QLabel {
                padding: 20px;
                border: 2px dashed #666;
                border-radius: 5px;
                color: #aaa;
            }
        """)
        self.form.addRow(warning)

        self.load_btn = QPushButton("📂 Загрузить .json файл настроек")
        StylesheetHelper.animate_button_click(self.load_btn)
        self.load_btn.clicked.connect(self._load_json_file_dialog)
        self.form.addRow(self.load_btn)
        StylesheetHelper.add_shadow(self.load_btn)

    def _load_json_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите файл настроек", "", "JSON файлы (*.json)")
        if path:
            # Отправляем сигнал в MainWindow для обработки копирования
            self.request_copy_settings_file_signal.emit(path, self.current_settings_path)

    def _load_json_into_form(self):
        self._clear_form()
        data = self.settings_manager.load_settings(self.current_settings_path)
        if data:
            for key, value in data.items():
                field = QLineEdit(str(value))
                field.editingFinished.connect(self._save_settings)
                self.fields[key] = field
                self.form.addRow(key, field)

    def _save_settings(self):
        if not self.current_script_name:
            return

        data = {key: field.text() for key, field in self.fields.items()}
        self.settings_manager.save_settings(self.current_settings_path, data)


class MainWindow(QMainWindow):
    """Main application window for Script Hub."""

    def __init__(self):
        super().__init__()
        self._script_logs: Dict[str, str] = {}  # Словарь для хранения только сессионных логов по скриптам
        # Удаляем _loaded_script_logs, так как мы никогда не будем автоматически подгружать логи из файла.
        # self._loaded_script_logs: Set[str] = set()
        self.current_script_name: Optional[str] = None  # Текущий активный скрипт
        self.running_script_name: Optional[str] = None  # Имя скрипта, который сейчас выполняется

        # Инициализация всех менеджеров
        self.script_operations = ScriptOperations()
        self.dependency_manager = DependencyManagement()
        self.script_executor = ScriptExecutor()
        self.settings_panel = SettingsPanel()
        self.script_manager_ui = ScriptManager()

        # В MainWindow.__init__
        self.github_manager = GitHubManager(SCRIPTS_ROOT_DIR, GITHUB_REPO_URL)
        self.github_manager.output_signal.connect(self.log_output)
        self.github_manager.update_finished_signal.connect(self._on_github_update_finished)

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(60 * 60 * 1000)  # Проверять каждый час (или раз в день)
        self.update_timer.timeout.connect(self._check_for_updates)

        # Проверяем наличие Git при запуске
        if self.github_manager._is_git_installed():
            # Если пользователь выбрал автообновление
            if self.settings_panel.get_setting("auto_update_scripts",
                                                 True):  # Предполагаем, что у вас есть settings_manager
                self.log_output("⚙️ Проверка обновлений скриптов при запуске...")
                self._check_for_updates()
                self.update_timer.start()  # Запускаем таймер для периодических проверок
            else:
                self.log_output("Автоматическое обновление скриптов отключено.")
        else:
            self.log_output("⚠️ Git не обнаружен. Автоматическое обновление скриптов невозможно.")


        # Инициализация кнопки очистки логов, ПЕРЕД вызовом _init_ui()
        self.clear_logs_button = QPushButton("🗑️ Очистить логи")
        self.clear_logs_button.clicked.connect(self._clear_current_script_logs)
        StylesheetHelper.animate_button_click(self.clear_logs_button)
        StylesheetHelper.add_shadow(self.clear_logs_button)

        self._init_ui()
        self._setup_connections()
        self._setup_window()
        self._load_initial_script_selection()

        if sys.platform == 'win32':
            set_dark_title_bar(self)

    def _init_ui(self):
        self.output_console = QTextEdit()
        self.output_console.setReadOnly(True)
        StylesheetHelper.add_shadow(self.output_console)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        StylesheetHelper.add_shadow(self.progress_bar)

        left_widget = self._create_left_widget()
        right_widget = self._create_right_widget()

        main_layout = QHBoxLayout()
        main_layout.addWidget(left_widget, 2)
        main_layout.addWidget(right_widget, 5)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def _setup_connections(self):
        # --- Connections from ScriptManager UI ---
        self.script_manager_ui.script_selected_signal.connect(self._on_script_selection_changed_in_ui)
        self.script_manager_ui.request_add_script_signal.connect(self._add_script_handler)
        self.script_manager_ui.request_delete_script_signal.connect(self._delete_script_handler)
        self.script_manager_ui.request_rename_script_signal.connect(self._rename_script_handler)
        self.script_manager_ui.request_change_settings_file_signal.connect(self._change_settings_file_handler)
        self.script_manager_ui.request_run_script_signal.connect(self._prepare_and_run_script)
        self.script_manager_ui.request_stop_script_signal.connect(self.script_executor.stop_script)
        self.script_manager_ui.log_output_signal.connect(self.log_output)  # Логи из ScriptManager

        # --- Connections from ScriptOperations ---
        self.script_operations.log_output_signal.connect(self.log_output)
        self.script_operations.script_deleted_signal.connect(self._on_script_deleted_by_operations)
        self.script_operations.script_renamed_signal.connect(self._on_script_renamed_by_operations)

        # --- Connections from ScriptExecutor ---
        self.script_executor.script_started_signal.connect(self._on_script_execution_started)
        self.script_executor.script_finished_signal.connect(self._on_script_execution_finished)
        self.script_executor.output_signal.connect(self.log_output)
        self.script_executor.error_signal.connect(self.log_output)

        # --- Connections from DependencyManagement ---
        self.dependency_manager.log_output_signal.connect(self.log_output)
        self.dependency_manager.progress_signal.connect(self._update_progress_bar)
        self.dependency_manager.venv_created_signal.connect(self._on_venv_created)
        self.dependency_manager.dependencies_installed_signal.connect(self._on_dependencies_installed)

        # --- Connections from SettingsPanel ---
        self.settings_panel.log_output_signal.connect(self.log_output)
        self.settings_panel.request_copy_settings_file_signal.connect(self._copy_settings_file_handler)

        # --- Connections from SettingsManager (internal to SettingsPanel, but could be direct if needed) ---
        self.settings_panel.settings_manager.log_output_signal.connect(self.log_output)

        # --- Connections from ScriptListManager (internal to ScriptManager, but could be direct if needed) ---
        self.script_manager_ui.script_list_manager.log_output_signal.connect(self.log_output)

        self.script_manager.scripts_loaded_signal.connect(self.script_manager_ui.load_scripts_to_ui)

    def _setup_window(self):
        self.setWindowTitle("Script Hub")
        self.setMinimumSize(1400, 800)
        self.setWindowIcon(QIcon('app_icon.ico'))

    def _create_left_widget(self) -> QWidget:
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.script_manager_ui)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)
        return left_widget

    def _create_right_widget(self) -> QWidget:
        right_layout = QVBoxLayout()

        # Заголовок и кнопка в одном горизонтальном лейауте
        log_header_layout = QHBoxLayout()
        log_header_layout.addWidget(QLabel("🖥️ Вывод скрипта"))
        log_header_layout.addStretch()  # Отталкивает кнопку вправо
        log_header_layout.addWidget(self.clear_logs_button)  # Добавляем кнопку

        right_layout.addLayout(log_header_layout)  # Добавляем этот лейаут
        right_layout.addWidget(self.output_console, 3)
        right_layout.addWidget(self.progress_bar)
        right_layout.addWidget(QLabel("⚙️ Настройки скрипта"))
        right_layout.addWidget(self.settings_panel, 2)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        return right_widget

    def _load_initial_script_selection(self):
        """Выбирает первый скрипт при старте, если он есть."""
        self.script_manager_ui.load_scripts_to_ui()  # Убедимся, что список загружен
        if self.script_manager_ui.script_list.count() > 0:
            self.script_manager_ui.script_list.setCurrentRow(0)
            # При первом запуске и выборе скрипта, консоль будет пустой,
            # так как self._script_logs[script_name] еще не существует.
            # Логи будут появляться только после запуска скрипта.
        else:  # Если нет скриптов, очищаем консоль и настройки
            self._on_script_selection_changed_in_ui("")  # Очистить текущий скрипт

    def _check_and_install_dependencies_then_run(self, script_name: str, script_dir: str, python_exec: str, script_path: str):
        """
        Вспомогательный метод для проверки зависимостей и запуска скрипта.
        Вызывается, когда Venv гарантированно доступно.
        """
        dependencies_ok = self.dependency_manager.check_dependencies(script_dir)

        if dependencies_ok:
            # Зависимости в порядке или requirements.txt отсутствует. Запускаем скрипт.
            self.script_executor.run_script(script_path, script_dir, python_exec, script_name)
        else:
            # Зависимости не удовлетворены. Предлагаем установить.
            reply = QMessageBox.question(
                self,
                "Требуются зависимости",
                f"Скрипт '{script_name}' требует установки или обновления зависимостей. Установить их?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.log_output("Начинаю установку зависимостей перед запуском...")
                # Запускаем установку. _on_dependencies_installed повторно вызовет этот метод.
                self.dependency_manager.install_dependencies(script_dir, python_exec)
            else:
                self.log_output("Запуск скрипта отменен пользователем.")

    def log_output(self, text: str):
        """Appends text to the output console and saves it to the current script's log file."""
        if self.current_script_name:
            # Добавляем текст к логам текущего скрипта в памяти (сессионные логи)
            if self.current_script_name not in self._script_logs:
                self._script_logs[self.current_script_name] = ""
            self._script_logs[self.current_script_name] += text + "\n"

            # Записываем в файл логов (основные логи)
            log_file_path = os.path.join(self.script_operations.get_script_dir(self.current_script_name),
                                         "script_log.txt")
            try:
                with open(log_file_path, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
            except Exception as e:
                # Если не удается записать в файл логов, хотя бы вывести ошибку
                self.output_console.append(f"❌ Ошибка записи в файл логов: {e}")

            # Обновляем QtextEdit, если это текущий активный скрипт
            self.output_console.append(text)
        else:
            # Если скрипт не выбран, просто выводим в консоль (для системных сообщений)
            self.output_console.append(text)

    def _clear_current_script_logs(self):
        """Очищает только отображаемую консоль для текущего выбранного скрипта,
        и сессионные логи в памяти, оставляя файл логов нетронутым."""
        if not self.current_script_name:
            QMessageBox.information(self, "Очистка логов", "Не выбран скрипт для очистки логов.")
            return

        # confirm = QMessageBox.question(
        #     self,
        #     "Очистить логи",
        #     f"Вы уверены, что хотите очистить отображаемые (сессионные) логи для скрипта '{self.current_script_name}'?\n\nФайл логов останется нетронутым.",
        #     QMessageBox.Yes | QMessageBox.No
        # )

        # if confirm == QMessageBox.Yes:
        # 1. Очищаем QTextEdit (сессионные логи в консоли)
        self.output_console.clear()

        # 2. Очищаем кэш логов в памяти для текущего скрипта.
        if self.current_script_name in self._script_logs:
            del self._script_logs[self.current_script_name]

            # self.log_output(f"✅ Отображаемые (сессионные) логи для '{self.current_script_name}' очищены.")
            # Файл логов (script_log.txt) остается нетронутым.

    def _update_progress_bar(self, value: int):
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(value > 0 and value < 100)
        if value == 100:
            QTimer.singleShot(1000, lambda: self.progress_bar.setVisible(False))

    def _display_script_logs(self, script_name: str):
        """
        Отображает только сессионные логи для указанного скрипта в output_console.
        Если сессионных логов нет (при первом выборе скрипта или после очистки),
        консоль будет пустой.
        """
        self.output_console.clear()
        if not script_name:
            return

        # Если логи уже в кэше (сессионные), отображаем их
        if script_name in self._script_logs:
            self.output_console.setText(self._script_logs[script_name])
        else:
            # Если логов нет в кэше, значит, это первый выбор в текущей сессии
            # или они были очищены. Мы не загружаем их из файла.
            # Консоль остается пустой, как и запрашивалось.
            pass

    # --- Handlers for ScriptManager UI signals ---

    def _on_script_selection_changed_in_ui(self, script_name: str):
        """Обрабатывает смену выбранного скрипта в UI списка."""
        self.current_script_name = script_name
        self.settings_panel.load_settings_for_script(script_name)
        self._display_script_logs(script_name)

        if script_name:
            # После смены скрипта, проверяем зависимости
            script_dir = self.script_operations.get_script_dir(script_name)
            self.dependency_manager.check_dependencies(
                script_dir)  # Это вызовет логирование через dependency_manager.log_output_signal

    def _add_script_handler(self, source_path: str):
        script_name = self.script_operations.add_script_file(source_path)
        if script_name:
            script_path = self.script_operations.get_script_path(script_name)
            script_dir = self.script_operations.get_script_dir(script_name)

            imports = self.dependency_manager.analyze_imports(script_path)
            if imports:
                self.dependency_manager.create_requirements_file(script_dir, imports)
                reply = QMessageBox.question(
                    self,
                    "Обнаружены зависимости",
                    f"Скрипт '{script_name}' использует следующие внешние зависимости:\n{', '.join(imports)}\n\nХотите установить их сейчас?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.dependency_manager.create_or_get_venv(script_dir)  # Начнет процесс Venv Creation
            else:
                self.log_output(f"ℹ️ Скрипт '{script_name}' не имеет внешних зависимостей.")

            # Обновляем UI списка скриптов и выбираем новый скрипт
            self.script_manager_ui.load_scripts_to_ui()
            self._on_script_selection_changed_in_ui(script_name)  # Это также обновит логи и настройки

    def _delete_script_handler(self, script_name: str):
        confirm = QMessageBox.question(self, "Удалить?",
                                       f"Вы уверены, что хотите удалить скрипт '{script_name}' и все его файлы (настройки, venv, логи)?")
        if confirm == QMessageBox.Yes:
            self.script_operations.delete_script_folder(script_name)  # Это отправит script_deleted_signal

    def _on_script_deleted_by_operations(self, script_name: str):
        """Реакция на сигнал об удалении скрипта от ScriptOperations."""
        if script_name in self._script_logs:
            del self._script_logs[script_name]  # Удаляем логи из памяти
        # self._loaded_script_logs теперь не используется
        self.script_manager_ui.load_scripts_to_ui()  # Обновляем список UI
        if self.current_script_name == script_name:
            self.current_script_name = None  # Сбрасываем текущий скрипт
            self.output_console.clear()
            self.settings_panel.load_settings_for_script("")  # Очищаем панель настроек

    def _rename_script_handler(self, old_name: str, new_name: str):
        if self.script_operations.rename_script_folder(old_name, new_name):  # Это отправит script_renamed_signal
            pass  # Дальнейшая логика в _on_script_renamed_by_operations

    def _on_script_renamed_by_operations(self, old_name: str, new_name: str):
        """Реакция на сигнал о переименовании скрипта от ScriptOperations."""
        if old_name in self._script_logs:
            self._script_logs[new_name] = self._script_logs.pop(old_name)  # Перемещаем логи в кэше
        # self._loaded_script_logs теперь не используется
        self.script_manager_ui.load_scripts_to_ui()  # Обновляем список UI
        if self.current_script_name == old_name:
            self.current_script_name = new_name
            self.settings_panel.load_settings_for_script(new_name)  # Обновляем настройки и логи

    def _change_settings_file_handler(self, script_name: str):
        settings_path = self.settings_panel.settings_manager.get_settings_path(script_name)
        self.settings_panel._load_json_file_dialog()  # Это запустит диалог и отправит request_copy_settings_file_signal

    def _copy_settings_file_handler(self, source_path: str, destination_path: str):
        if self.settings_panel.settings_manager.copy_settings_file(source_path, destination_path):
            self.settings_panel._load_json_into_form()  # Обновляем форму настроек после копирования

    # --- Handlers for ScriptExecutor signals ---
    def _on_script_execution_started(self, script_name: str):
        self.running_script_name = script_name
        self.script_manager_ui.set_run_stop_button_states(True)

    def _on_script_execution_finished(self, script_name: str):
        self.running_script_name = None
        self.script_manager_ui.set_run_stop_button_states(False)

    # --- Handlers for DependencyManagement signals ---
    def _on_venv_created(self, script_dir: str, python_exec_path: str):
        self.log_output(f"✅ Виртуальное окружение готово для {os.path.basename(script_dir)}.")
        # После создания venv, запускаем установку зависимостей
        self.dependency_manager.install_dependencies(script_dir, python_exec_path)

    # А затем _on_dependencies_installed должен выглядеть так:
    def _on_dependencies_installed(self, script_name: str, success: bool):
        if success:
            self.log_output("✅ Установка зависимостей завершена успешно.")
            # После успешной установки, повторно вызываем _prepare_and_run_script
            # для текущего скрипта. Он теперь должен пройти проверку зависимостей.
            if script_name == self.current_script_name:  # Убедиться, что это тот же скрипт
                self.log_output("Повторяю попытку запуска скрипта после установки зависимостей...")
                # Важно: вызываем _prepare_and_run_script, а не _check_and_install_dependencies_then_run,
                # потому что _prepare_and_run_script инициирует весь процесс, включая получение python_exec.
                self._prepare_and_run_script(script_name)
            else:
                self.log_output(f"DEBUG: Установка зависимостей завершена для другого скрипта ({script_name}).")

        else:
            self.log_output(f"❌ Установка зависимостей для '{script_name}' завершилась с ошибками.")
        self.dependency_manager.clear_packages_cache()
        self.progress_bar.setValue(0)  # Убедимся, что прогресс бар сбрасывается.
        self.progress_bar.setVisible(False)  # Скрыть прогресс бар

    def _on_venv_ready_to_check_deps(self, script_dir: str, python_exec_path: str):
        """
        Этот метод вызывается, когда виртуальное окружение либо только что создано,
        либо было найдено (если оно еще не было обработано).
        Теперь мы можем проверить зависимости и запустить скрипт.
        """
        self.log_output(f"DEBUG: Venv готово ({os.path.basename(script_dir)}). Проверяю зависимости...")

        # Убедитесь, что мы работаем с текущим скриптом, если несколько Venv обрабатываются одновременно.
        # (Хотя ваша UI не позволяет запускать несколько скриптов одновременно)
        current_script_dir = self.script_operations.get_script_dir(self.current_script_name)
        if script_dir != current_script_dir:
            self.log_output(f"DEBUG: Venv готово для другого скрипта ({os.path.basename(script_dir)}), игнорирую.")
            return

        script_name = self.current_script_name  # Используем текущий выбранный скрипт
        script_path = self.script_operations.get_script_path(script_name)

        self._check_and_install_dependencies_then_run(script_name, script_dir, python_exec_path)

    def _prepare_and_run_script(self, script_name: str):
        script_path = self.script_operations.get_script_path(script_name)
        script_dir = self.script_operations.get_script_dir(script_name)

        if not script_path:
            self.log_output(f"❌ Файл скрипта 'script.py' не найден в '{script_name}'.")
            return

        # Шаг 1: Убедиться, что виртуальное окружение существует и получить python_exec.
        # Этот вызов ИНИЦИИРУЕТ создание Venv, если его нет.
        # Если Venv УЖЕ ЕСТЬ, он вернет python_exec сразу.
        # Если Venv НЕТ, он запустит поток создания и вернет None.
        python_exec = self.dependency_manager.create_or_get_venv(script_dir)

        if python_exec:
            # Если python_exec доступен СРАЗУ (т.е. Venv уже существовало),
            # то переходим к Шагу 2: проверке и установке зависимостей.
            self._check_and_install_dependencies_then_run(script_name, script_dir, python_exec, script_path)
        else:
            # Если python_exec был None, значит, Venv создается в потоке.
            # Мы ничего не делаем здесь, а ждем сигнала venv_created_signal.
            # _on_venv_ready_to_check_deps будет вызван, когда Venv будет готово.
            self.log_output("Ожидаю создания виртуального окружения для запуска скрипта...")

    def _on_github_update_finished(self, success: bool, message: str):
        if success:
            self.log_output(f"🟢 Обновление скриптов с GitHub: {message}")
            self.script_manager_ui.load_scripts_to_ui()  # Обновить UI после синхронизации скриптов
            # Если вы хотите автоматически запускать venv/установку зависимостей для новых скриптов
            # это будет сложнее, так как нужно итерировать по новым скриптам.
            # Для начала, пусть пользователь запустит их вручную.
        else:
            self.log_output(f"🔴 Ошибка обновления скриптов с GitHub: {message}")

    def _check_for_updates(self):
        if self.settings_manager.get_setting("auto_update_scripts", True):
            self.github_manager.check_and_update_repository()
        else:
            self.update_timer.stop()  # Если автообновление отключено, останавливаем таймер
            self.log_output("Автоматическое обновление скриптов отключено.")

# Функции вне класса (если они не являются методами класса)
def set_dark_title_bar(window):
    """Sets dark title bar for Windows 10/11."""
    try:
        hwnd = window.winId().__int__()
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = wintypes.BOOL(True)

        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
    except Exception as e:
        print(f"Не удалось установить темную тему: {e}")
        window.setStyleSheet("""
            QMainWindow {
                border: 1px solid #444;
            }
            QWidget {
                background-color: #1a1a1a;
            }
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        with open("styles.qss", "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("styles.qss not found. Using default styles.")
    except Exception as e:
        print(f"Error loading stylesheet: {e}")

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())