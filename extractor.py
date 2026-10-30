import asyncio
import json
import re
import os
import sys
import codecs
import datetime
import time
import traceback
import xml.etree.ElementTree as ET
import hashlib
import html as html_module
from pathlib import Path
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit
from colorama import Fore, Style, init
from playwright.async_api import (
    async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError,
)

if sys.platform == 'win32':
    import msvcrt

    def masked_input(prompt=""):
        sys.stdout.write(prompt)
        sys.stdout.flush()
        chars = []
        while True:
            ch = msvcrt.getwch()
            if ch in ('\r', '\n'):
                sys.stdout.write('\n')
                sys.stdout.flush()
                break
            elif ch == '\x08':
                if chars:
                    chars.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            elif ch == '\x03':
                raise KeyboardInterrupt
            elif ch == '\x1a':
                raise EOFError
            elif ch in ('\x00', '\xe0'):
                msvcrt.getwch()
            else:
                chars.append(ch)
                sys.stdout.write('*')
                sys.stdout.flush()
        return ''.join(chars)
else:
    import termios
    import tty

    def masked_input(prompt=""):
        sys.stdout.write(prompt)
        sys.stdout.flush()
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        chars = []
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in ('\r', '\n'):
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    break
                elif ch == '\x7f':
                    if chars:
                        chars.pop()
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                elif ch == '\x03':
                    raise KeyboardInterrupt
                elif ch == '\x04':
                    raise EOFError
                else:
                    chars.append(ch)
                    sys.stdout.write('*')
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ''.join(chars)

init(autoreset=True)

CONFIG_DIR = Path("configs")
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = CONFIG_DIR / "settings.json"

STRINGS = {
    'th': {
        'exercises_catalog_summary': '[*] พบ {lessons} Lesson / {exercises} แบบฝึกหัดหลังสแกนทั้งบท',
        'exercises_catalog_incomplete': '[!] ยังยืนยันรายการครบไม่ได้: บาง Lesson/รายการเดิมยังไม่โหลด หรือสแกนไม่จบ รายการนี้อาจมีข้อมูลเดิม กรุณากด R เพื่อโหลดใหม่',
        'exercises_refresh': 'โหลดรายชื่อแบบฝึกหัดทั้งหมดใหม่',
        'exercises_scan_progress': '[*] กำลังรวมรายการทั้งบท: {lessons} Lesson / {exercises} แบบฝึกหัด (ยังตรวจความครบถ้วนอยู่)',
        'exercises_verifying': '[*] กำลังตรวจสอบว่าเว็บเปิดแบบฝึกหัดที่เลือก: {name}',
        'exercises_mismatch': '[-] ยืนยันแบบฝึกหัดไม่ได้: เลือก "{expected}" แต่หน้าเว็บแสดง "{actual}" จึงไม่อ่านหรือบันทึกคำตอบ',
        'exercises_ambiguous': '[-] ไม่พบแบบฝึกหัดที่ตรงกันเพียงรายการเดียวในบท/Lesson ที่เลือก: {name}',
        'exercises_returned': '[+] กลับสู่หน้าเลือกแบบฝึกหัดแล้ว',
        'exercises_return_failed': '[-] กลับหน้า Workbook ไม่สำเร็จ กรุณาตรวจสอบหน้าเว็บแล้วลองเลือกคอร์สใหม่',
        'cached_legacy_warning': '[!] ข้อมูลนี้มาจากรุ่นที่ยังไม่ได้ยืนยันชื่อแบบฝึกหัด ควรเลือกแบบฝึกหัดและดึงข้อมูลใหม่ก่อนใช้งาน',
        'cached_unverified': '[!] ข้อมูลเดิมยังไม่ได้ยืนยันชื่อแบบฝึกหัด หรือเป็นคนละ Lesson โปรแกรมจะดึงใหม่เพื่อป้องกันการแสดงคำตอบผิด (ข้อมูลเดิมยังดูได้ในเมนูฐานข้อมูล)',
        'datajs_waiting': '[*] กำลังรอไฟล์คำตอบ: รับแล้ว {received}/{total} ไฟล์ (ผ่านไป {seconds:.0f} วินาที)',
        'datajs_received': '[+] รับไฟล์คำตอบแล้ว ({size:,} ไบต์)',
        'datajs_downloading': '[*] กำลังดาวน์โหลดไฟล์คำตอบ {n}/{total}...',
        'datajs_decoding': '[*] กำลังถอดรหัสข้อมูลคำตอบ {n}/{total}...',
        'datajs_decoded': '[+] ถอดรหัสข้อมูลสำเร็จ พบ XML {n} ไฟล์',
        'datajs_http_failed': '[!] โหลดไฟล์คำตอบไม่สำเร็จ (HTTP {status})',
        'datajs_read_failed': '[!] อ่านไฟล์คำตอบไม่สำเร็จ ({error}) จะลองรับข้อมูลใหม่ถ้ายังมีเวลา',
        'xml_progress': '[*] ถอดรหัสและอ่านคำตอบ XML {n}/{total}: {name}',
        'summary_save_failed': '[-] อ่านคำตอบได้ แต่บันทึกลงฐานข้อมูลไม่สำเร็จ',
        'progress_active': '[*] ยังทำงานอยู่: {stage} (ผ่านไป {seconds:.0f} วินาที)',
        'stage_open_exercise': 'กำลังเปิดและตรวจสอบแบบฝึกหัด',
        'stage_return_workbook': 'กำลังกลับหน้า Workbook และโหลดรายการแบบฝึกหัด',
        'stage_download': 'กำลังดาวน์โหลดไฟล์คำตอบ',
        'stage_decode': 'กำลังถอดรหัสข้อมูลคำตอบ',
        'stage_xml': 'กำลังอ่านคำตอบจาก XML',
        'stage_exercises': 'กำลังรอรายการแบบฝึกหัดในบทที่เลือก',
        'navigation_retry': '[*] หน้าเว็บกำลังเปลี่ยน รอแล้วลองอ่านข้อมูลอีกครั้ง ({n}/3)',
        'input_enter_exercises': '[>] กด Enter เพื่อกลับหน้าเลือกแบบฝึกหัด...',

        'ui_title': 'Login & แสดงเฉลยจากแบบฝึกหัด',
        'ui_view_db': 'ดูฐานข้อมูล',
        'ui_change_lang': 'เปลี่ยนภาษา (TH/EN)',
        'ui_exit': 'ออกจากโปรแกรม',
        'ui_menu_header': 'เมนูหลัก',

        'accounts_header': 'บัญชี Cambridge One / Chrome profiles',
        'accounts_empty': '[!] ยังไม่มีบัญชีในระบบ',
        'accounts_add': 'เพิ่มบัญชีใหม่',
        'accounts_cancel': 'ยกเลิก',
        'accounts_select': 'เลือก',
        'accounts_new_email': 'Email บัญชีใหม่',
        'accounts_invalid_email': '[-] Email ไม่ถูกต้อง',
        'accounts_added': '[+] เพิ่มบัญชี {email} แล้ว',
        'accounts_invalid_choice': '[-] ตัวเลือกไม่ถูกต้อง',
        'accounts_saved_pwd': '[saved password]',

        'login_opening_profile': '[*] กำลังเปิด Chrome profile: {path}',
        'login_browser_opened': '[+] เปิดเบราว์เซอร์แบบเก็บ session แล้ว',
        'login_checking_session': '[*] กำลังตรวจสอบ session...',
        'login_current_url': '[*] URL ปัจจุบัน: {url}',
        'login_session_ok': '[+] Session ยังใช้งานได้',
        'login_use_saved_pwd': '[+] ใช้รหัสผ่านที่บันทึกไว้',
        'login_enter_pwd': '[>] Password ของ {email}: ',
        'login_save_pwd_q': '[>] บันทึกรหัสผ่าน? (1=yes / 0=no): ',
        'login_pwd_saved': '[+] บันทึกรหัสผ่านแล้ว',
        'login_no_pwd': '[-] ไม่ได้ใส่รหัสผ่าน',
        'login_logging_in': '[*] Logging in...',
        'login_success': '[+] Login successful!',
        'login_failed': '[-] Login ไม่สำเร็จ',
        'login_cancel': '[!] ยกเลิก',

        'courses_header': 'คอร์สที่มี Digital Workbook',
        'courses_not_found': '[!] ไม่พบคอร์ส',
        'courses_select': 'เลือกคอร์ส:',
        'courses_refresh': 'รีเฟรชรายการคอร์ส',
        'courses_exit': 'ออกจากโปรแกรม',
        'courses_found': '[+] พบ {n} คอร์ส',
        'courses_opening': '[*] กำลังเปิด Digital Workbook: {name}',
        'courses_opened': '[+] คลิก Digital Workbook สำเร็จ',
        'courses_open_failed': '[-] ไม่พบ Digital Workbook',
        'courses_fetching': '[*] Fetching courses with Digital Workbooks...',

        'units_header': 'เลือกบทที่ต้องการดู',
        'units_not_found': '[!] ไม่พบบทเรียน',
        'units_back': 'กลับไปเลือกคอร์สใหม่',
        'units_select': 'เลือกบท (ตัวเลข): ',
        'units_loading': '[*] กำลังโหลด Units...',
        'units_found': '[+] พบ {n} บทเรียน',
        'units_opening': '[*] กำลังเปิดบท: {name}',
        'units_opened': '[+] เปิดบทสำเร็จ',
        'units_open_failed': '[-] ไม่พบบทนี้',
        'units_exercises_fetching': '[*] Fetching exercises in: {name}',
        'units_exercises_found': '[+] พบ {n} Lesson',

        'exercises_back': 'กลับไปเลือกบทใหม่',
        'exercises_select': 'เลือกแบบฝึกหัด (ตัวเลข): ',
        'exercises_none': '[!] ไม่มีแบบฝึกหัด',
        'exercises_selected': '[*] เลือก: {name}',
        'exercises_opening': '[*] กำลังเปิดแบบฝึกหัด: {name}',
        'exercises_opened': '[+] เปิดแบบฝึกหัดสำเร็จ',
        'exercises_open_failed': '[-] ไม่พบแบบฝึกหัดนี้',
        'exercises_already_open': '[+] อยู่ในหน้าแบบฝึกหัดข้อนี้เรียบร้อยแล้ว',
        'exercises_back_workbook': '[*] กำลังย้อนกลับสู่หน้า Workbook...',

        'cached_found': '[+] พบข้อมูลในฐานข้อมูล (saved at {time})',
        'cached_use_q': '[>] ใช้ข้อมูลที่บันทึกไว้? (1=yes / 0=no): ',
        'cached_header': 'เฉลยจากฐานข้อมูล: {name}',
        'datajs_fetching': '[*] กำลังดึงฐานข้อมูลคำตอบ',
        'datajs_not_found': '[-] ไม่พบ data.js',
        'datajs_parse_failed': '[-] ไม่สามารถแกะ data.js ได้',
        'answers_header': 'เฉลยแบบฝึกหัด: {name}',

        'printq_context': 'Context',
        'printq_audio': 'Audio',
        'printq_options': 'Options',
        'printq_correct': 'Correct',
        'printq_correct_id': 'Correct (id)',
        'printq_not_found': 'text not found',
        'printq_questions': 'questions',
        'summary': 'Summary',
        'summary_processed': 'processed',
        'summary_skipped': 'skipped',
        'summary_saved': '[+] saved to database',
        'summary_skip_finished': '[skip] {name} - activity finished',
        'summary_skip_noans': '[skip] {name} - no answers found',

        'db_empty': '[!] ฐานข้อมูลว่างเปล่า',
        'db_header': 'ฐานข้อมูลคำตอบ (ทั้งหมด {n} รายการ)',
        'db_saved_at': 'บันทึกเมื่อ',
        'db_xml_count': 'จำนวน XML',
        'db_select_view': 'เลือกหมายเลขเพื่อดูรายละเอียด (หรือ Enter เพื่อกลับ): ',
        'db_invalid_number': '[-] หมายเลขไม่ถูกต้อง',
        'db_enter_number': '[-] กรุณาใส่ตัวเลข',

        'input_enter_back': '[>] กด Enter เพื่อกลับ...',
        'input_enter_close': '[>] กด Enter เพื่อปิดเบราว์เซอร์...',
        'input_enter': '[>] กด Enter...',
        'input_choice': '[>] Enter choice: ',
        'input_invalid': 'ตัวเลือกไม่ถูกต้อง กรุณาเลือก 1-4',
        'input_number': '[-] กรุณาใส่ตัวเลข',

        'closing_browser': '[*] กำลังปิดเบราว์เซอร์...',
        'closed_browser': '[+] ปิดเบราว์เซอร์เรียบร้อย',
        'exit_program': '[*] กำลังออกจากโปรแกรม...',
        'goodbye': 'ลาก่อน!',
        'error_prefix': '[-] Error: {msg}',
        'fatal_prefix': '[-] Fatal Error: {msg}',
        'log_saved': '[*] log saved to: {path}',
        'log_session': 'Session log: {path}',
        'db_loaded': '[+] database loaded ({n} entries)',

        'lang_current': 'ภาษาปัจจุบัน: ไทย',
        'lang_switched': '[+] เปลี่ยนภาษาเป็น ไทย เรียบร้อย',
        'lang_menu_header': 'เลือกภาษา',
        'lang_th': 'ภาษาไทย',
        'lang_en': 'English',
        'lang_back': 'กลับเมนูหลัก',
    },
    'en': {
        'exercises_catalog_summary': '[*] Found {lessons} lessons / {exercises} exercises after scanning the unit',
        'exercises_catalog_incomplete': '[!] Catalog completeness is unconfirmed: a lesson/previous entry is missing, or scanning did not finish. Some entries may be from an earlier scan. Press R to retry.',
        'exercises_refresh': 'Reload the full exercise catalog',
        'exercises_scan_progress': '[*] Collecting the full unit: {lessons} lessons / {exercises} exercises (completeness check in progress)',
        'exercises_verifying': '[*] Verifying the exercise opened in the browser: {name}',
        'exercises_mismatch': '[-] Could not verify exercise: selected "{expected}", browser shows "{actual}". Answers will not be read or saved.',
        'exercises_ambiguous': '[-] Could not find exactly one matching exercise in the selected unit/lesson: {name}',
        'exercises_returned': '[+] Returned to the exercise selection page',
        'exercises_return_failed': '[-] Could not return to the Workbook. Check the browser and try selecting the course again.',
        'cached_legacy_warning': '[!] This entry was saved without verifying the exercise identity. Select the exercise and fetch it again before use.',
        'cached_unverified': '[!] Saved data has no verified exercise identity, or belongs to another lesson. Fetching again to avoid incorrect answers (the old entry remains available in View Database).',
        'datajs_waiting': '[*] Waiting for answer files: received {received}/{total} (elapsed {seconds:.0f}s)',
        'datajs_received': '[+] Answer file received ({size:,} bytes)',
        'datajs_downloading': '[*] Downloading answer file {n}/{total}...',
        'datajs_decoding': '[*] Decoding answer data {n}/{total}...',
        'datajs_decoded': '[+] Answer data decoded: {n} XML files found',
        'datajs_http_failed': '[!] Answer file download failed (HTTP {status})',
        'datajs_read_failed': '[!] Could not read answer file ({error}); will retry if time remains',
        'xml_progress': '[*] Decoding and reading answer XML {n}/{total}: {name}',
        'summary_save_failed': '[-] Answers were read, but could not be saved to the database',
        'progress_active': '[*] Still working: {stage} (elapsed {seconds:.0f}s)',
        'stage_open_exercise': 'opening and verifying the exercise',
        'stage_return_workbook': 'returning to the Workbook and loading exercises',
        'stage_download': 'downloading answer files',
        'stage_decode': 'decoding answer data',
        'stage_xml': 'reading answers from XML',
        'stage_exercises': 'waiting for exercises in the selected unit',
        'navigation_retry': '[*] Page is navigating; waiting and retrying the read ({n}/3)',
        'input_enter_exercises': '[>] Press Enter to return to the exercise selection page...',

        'ui_title': 'Login & Show Answers from Exercises',
        'ui_view_db': 'View Database',
        'ui_change_lang': 'Change Language (TH/EN)',
        'ui_exit': 'Exit',
        'ui_menu_header': 'Main Menu',

        'accounts_header': 'Cambridge One Accounts / Chrome profiles',
        'accounts_empty': '[!] No accounts yet',
        'accounts_add': 'Add new account',
        'accounts_cancel': 'Cancel',
        'accounts_select': 'Select',
        'accounts_new_email': 'New account email',
        'accounts_invalid_email': '[-] Invalid email',
        'accounts_added': '[+] Added account {email}',
        'accounts_invalid_choice': '[-] Invalid choice',
        'accounts_saved_pwd': '[saved password]',

        'login_opening_profile': '[*] Opening Chrome profile: {path}',
        'login_browser_opened': '[+] Browser opened with saved session',
        'login_checking_session': '[*] Checking session...',
        'login_current_url': '[*] Current URL: {url}',
        'login_session_ok': '[+] Session still valid',
        'login_use_saved_pwd': '[+] Using saved password',
        'login_enter_pwd': '[>] Password for {email}: ',
        'login_save_pwd_q': '[>] Save password? (1=yes / 0=no): ',
        'login_pwd_saved': '[+] Password saved',
        'login_no_pwd': '[-] No password entered',
        'login_logging_in': '[*] Logging in...',
        'login_success': '[+] Login successful!',
        'login_failed': '[-] Login failed',
        'login_cancel': '[!] Cancelled',

        'courses_header': 'Courses with Digital Workbook',
        'courses_not_found': '[!] No courses found',
        'courses_select': 'Select course:',
        'courses_refresh': 'Refresh course list',
        'courses_exit': 'Exit program',
        'courses_found': '[+] Found {n} courses',
        'courses_opening': '[*] Opening Digital Workbook: {name}',
        'courses_opened': '[+] Digital Workbook clicked',
        'courses_open_failed': '[-] Digital Workbook not found',
        'courses_fetching': '[*] Fetching courses with Digital Workbooks...',

        'units_header': 'Select a unit',
        'units_not_found': '[!] No units found',
        'units_back': 'Back to course selection',
        'units_select': 'Select unit (number): ',
        'units_loading': '[*] Loading Units...',
        'units_found': '[+] Found {n} units',
        'units_opening': '[*] Opening unit: {name}',
        'units_opened': '[+] Unit opened',
        'units_open_failed': '[-] Unit not found',
        'units_exercises_fetching': '[*] Fetching exercises in: {name}',
        'units_exercises_found': '[+] Found {n} Lesson(s)',

        'exercises_back': 'Back to unit selection',
        'exercises_select': 'Select exercise (number): ',
        'exercises_none': '[!] No exercises',
        'exercises_selected': '[*] Selected: {name}',
        'exercises_opening': '[*] Opening exercise: {name}',
        'exercises_opened': '[+] Exercise opened',
        'exercises_open_failed': '[-] Exercise not found',
        'exercises_already_open': '[+] Already in this exercise page',
        'exercises_back_workbook': '[*] Going back to Workbook...',

        'cached_found': '[+] Found in database (saved at {time})',
        'cached_use_q': '[>] Use saved data? (1=yes / 0=no): ',
        'cached_header': 'Answers from database: {name}',
        'datajs_fetching': '[*] Fetching answer database',
        'datajs_not_found': '[-] data.js not found',
        'datajs_parse_failed': '[-] Failed to parse data.js',
        'answers_header': 'Exercise answers: {name}',

        'printq_context': 'Context',
        'printq_audio': 'Audio',
        'printq_options': 'Options',
        'printq_correct': 'Correct',
        'printq_correct_id': 'Correct (id)',
        'printq_not_found': 'text not found',
        'printq_questions': 'questions',
        'summary': 'Summary',
        'summary_processed': 'processed',
        'summary_skipped': 'skipped',
        'summary_saved': '[+] saved to database',
        'summary_skip_finished': '[skip] {name} - activity finished',
        'summary_skip_noans': '[skip] {name} - no answers found',

        'db_empty': '[!] database is empty',
        'db_header': 'answers database (total {n} entries)',
        'db_saved_at': 'saved at',
        'db_xml_count': 'XML count',
        'db_select_view': 'select number to view details (or Enter to return): ',
        'db_invalid_number': '[-] invalid number',
        'db_enter_number': '[-] please enter a number',

        'input_enter_back': '[>] Press Enter to return...',
        'input_enter_close': '[>] Press Enter to close browser...',
        'input_enter': '[>] Press Enter...',
        'input_choice': '[>] Enter choice: ',
        'input_invalid': 'Invalid choice, please select 1-4',
        'input_number': '[-] Please enter a number',

        'closing_browser': '[*] Closing browser...',
        'closed_browser': '[+] Browser closed',
        'exit_program': '[*] Exiting program...',
        'goodbye': 'Goodbye!',
        'error_prefix': '[-] Error: {msg}',
        'fatal_prefix': '[-] Fatal Error: {msg}',
        'log_saved': '[*] log saved to: {path}',
        'log_session': 'Session log: {path}',
        'db_loaded': '[+] database loaded ({n} entries)',

        'lang_current': 'Current language: English',
        'lang_switched': '[+] Language switched to English',
        'lang_menu_header': 'Select language',
        'lang_th': 'Thai',
        'lang_en': 'English',
        'lang_back': 'Back to main menu',
    },
}

class Lang:
    current = 'th'

    @classmethod
    def load(cls):
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    s = json.load(f)
                lang = s.get('language', 'th')
                if lang in ('th', 'en'):
                    cls.current = lang
        except Exception:
            pass

    @classmethod
    def save(cls):
        try:
            data = {}
            if SETTINGS_FILE.exists():
                try:
                    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data['language'] = cls.current
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def t(key, **kwargs):
    s = STRINGS.get(Lang.current, STRINGS['th']).get(key)
    if s is None:
        s = STRINGS['th'].get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s

async def console_input(prompt, reader=None):
    # Keep Playwright's event loop running while the user works in the browser.
    return await asyncio.to_thread(reader or input, prompt)


@asynccontextmanager
async def report_progress(stage_key, interval=3):
    """Emit log-friendly heartbeats without blocking browser/network callbacks."""
    started = time.monotonic()

    async def heartbeat():
        while True:
            await asyncio.sleep(interval)
            print(f"  {Fore.CYAN}{t('progress_active', stage=t(stage_key), seconds=time.monotonic() - started)}{Style.RESET_ALL}", flush=True)

    task = asyncio.create_task(heartbeat())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def normalized_name(value):
    return sigma_normalizetext(value or '').casefold()


def cache_matches_exercise(entry, exercise, unit_name):
    """Legacy caches may contain answers saved under a substring-matched name."""
    source = entry.get('source') or {}
    if source.get('verification_version') != 1:
        return False
    for actual, expected in (
        (source.get('verified_title'), exercise['name']),
        (entry.get('exercise'), exercise['name']),
        (entry.get('lesson'), exercise['lesson']),
        (entry.get('unit'), unit_name),
        (source.get('unit'), unit_name),
        (source.get('lesson'), exercise['lesson']),
    ):
        if normalized_name(actual) != normalized_name(expected):
            return False
    if exercise.get('href') and source.get('href') != exercise['href']:
        return False
    return True


def exercise_identity(exercise):
    """Stable across scrolls/re-renders; never use a transient DOM marker as an ID."""
    return (normalized_name(exercise['name']), exercise.get('href') or '', exercise.get('activity_id') or '')


def catalog_signature(data):
    return tuple(sorted(
        (normalized_name(lesson['name']), exercise_identity(exercise))
        for lesson in data.get('lessons', []) for exercise in lesson['exercises']
    ))


def merge_exercise_catalogs(previous, current):
    """Union snapshots without losing lessons that a virtual scroller unmounted."""
    result = {'unit_name': current['unit_name'], 'lessons': [], 'discovery': dict(current.get('discovery', {}))}
    lessons = {}
    for snapshot in (previous or {}, current):
        for lesson in snapshot.get('lessons', []):
            key = normalized_name(lesson['name'])
            if key not in lessons:
                lessons[key] = {'name': lesson['name'], 'exercises': []}
            target = lessons[key]['exercises']
            for exercise in lesson['exercises']:
                identity = exercise_identity(exercise)
                index = next((i for i, existing in enumerate(target) if exercise_identity(existing) == identity), None)
                if index is None:
                    target.append(dict(exercise))
                else:
                    target[index] = dict(exercise)
    # Cambridge lessons are lettered; discovery may start at D after returning
    # from an exercise. Do not let the initial viewport determine menu numbering.
    result['lessons'] = sorted(lessons.values(), key=lambda lesson: normalized_name(lesson['name']))
    headers = list(dict.fromkeys(
        name for snapshot in (previous or {}, current)
        for name in snapshot.get('discovery', {}).get('lesson_headers', [])
    ))
    result['discovery']['lesson_headers'] = sorted(headers, key=normalized_name)
    result['discovery']['missing_lessons'] = [
        name for name in headers
        if not lessons.get(normalized_name(name), {}).get('exercises')
    ]
    return result


def UI_TEXT():
    return f"""
{Fore.GREEN}
                                                         
   ▄▄▄▄▄▄▄                                                 
  ███▀▀▀▀▀        ██                      ██               
  ███▄▄    ██ ██ ▀██▀▀ ████▄  ▀▀█▄ ▄████ ▀██▀▀ ▄███▄ ████▄ 
  ███       ███   ██   ██ ▀▀ ▄█▀██ ██     ██   ██ ██ ██ ▀▀ 
  ▀███████ ██ ██  ██   ██    ▀█▄██ ▀████  ██   ▀███▀ ██    
                                                                                                                                                             
{Style.RESET_ALL}
  by z3nTr4ry

  ---------------------------------
  1. {t('ui_title')}
  2. {t('ui_view_db')}
  3. {t('ui_change_lang')}
  4. {t('ui_exit')}
  --------------------------------
"""

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

class SkibidiLogger:
    def __init__(self, log_dir="logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.log_file = self.log_dir / f"session_{ts}.log"
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        try:
            # Fast restarts used to overwrite a previous session in the same
            # second. Use a unique timestamp AND exclusive creation.
            suffix = 0
            while True:
                try:
                    self.file = open(self.log_file, 'x', encoding='utf-8')
                    break
                except FileExistsError:
                    suffix += 1
                    self.log_file = self.log_dir / f"session_{ts}_{suffix}.log"
        except Exception:
            self.file = None
            self.original_stdout.write(
                f"[!] cannot open log file: {self.log_file}\n"
            )

    def write(self, message):
        try:
            self.original_stdout.write(message)
        except Exception:
            pass
        if self.file:
            try:
                clean = re.sub(r'\x1b\[[0-9;]*m', '', message)
                self.file.write(clean)
                self.file.flush()
            except Exception:
                pass

    def flush(self):
        try:
            self.original_stdout.flush()
        except Exception:
            pass
        if self.file:
            try:
                self.file.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def close(self):
        if self.file:
            try:
                self.file.close()
            except Exception:
                pass

class PomlikeheeyaDB:
    def __init__(self, db_file="configs/answers_db.json"):
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self):
        try:
            if self.db_file.exists():
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"{Fore.YELLOW}  [!] cannot load database: {e}{Style.RESET_ALL}")
        return {}

    def _save(self):
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"{Fore.RED}  [!] cannot save database: {e}{Style.RESET_ALL}")
            return False

    def skibidikey(self, course, unit, exercise, lesson=None):
        raw = f"{course}||{unit}||{exercise}"
        if lesson:
            raw += f"||{lesson}"
        return hashlib.sha256(raw.strip().encode('utf-8')).hexdigest()[:20]

    def get(self, course, unit, exercise, lesson=None):
        entry = self.data.get(self.skibidikey(course, unit, exercise, lesson))
        if entry is None and lesson:
            # Retain legacy entries for manual viewing, but never trust them silently.
            entry = self.data.get(self.skibidikey(course, unit, exercise))
        return entry

    def set(self, course, unit, exercise, answers, lesson=None, source=None):
        key = self.skibidikey(course, unit, exercise, lesson)
        self.data[key] = {
            'course': course,
            'unit': unit,
            'exercise': exercise,
            'lesson': lesson,
            'source': source or {},
            'saved_at': datetime.datetime.now().isoformat(),
            'answers': answers,
        }
        return self._save()

    def list_all(self):
        return self.data

    def count(self):
        return len(self.data)

def sigma_normalizetext(text):
    if not text:
        return ""
    text = text.replace('â€™', "'").replace('â€œ', '"').replace('â€', '"')
    text = text.replace('â€“', '-').replace('â€˜', "'").replace('â', "'")
    replacements = {
        '\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00a0': ' ',
        '\u200b': '', '`': "'",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def rizz_decodeunicode(text):
    res = text
    try:
        res = codecs.decode(text, 'unicode_escape')
    except Exception:
        try:
            res = html_module.unescape(codecs.decode(text, 'unicode_escape'))
        except Exception:
            try:
                res = text.encode('latin-1', 'backslashreplace').decode('unicode_escape')
            except Exception:
                res = text
    return sigma_normalizetext(res)

def skibidi_detectns(root):
    tag = root.tag
    if '}' in tag:
        return tag.split('}')[0] + '}'
    return ''

def gyattfindallns(root, local_name):
    ns = skibidi_detectns(root)
    results = []
    if ns:
        results = root.findall(f'.//{ns}{local_name}')
    if not results:
        results = root.findall(f'.//{local_name}')
    return results

def ohiofindns(root, local_name, attr_id=None):
    ns = skibidi_detectns(root)
    if ns:
        if attr_id:
            for el in root.iter(f'{ns}{local_name}'):
                if el.get('id') == attr_id:
                    return el
        else:
            el = root.find(f'.//{ns}{local_name}')
            if el is not None:
                return el
    if attr_id:
        for el in root.iter(local_name):
            if el.get('id') == attr_id:
                return el
    else:
        el = root.find(f'.//{local_name}')
        if el is not None:
            return el
    return None

def sigma_isfinished(xml_content):
    return "You have finished the activity." in xml_content

def rizz_extractrubric(root):
    rubric = ohiofindns(root, 'div', 'rubric')
    if rubric is None:
        return ''
    for p in rubric.iter():
        tag = p.tag.split('}')[-1] if '}' in p.tag else p.tag
        if tag == 'p':
            text = ''.join(p.itertext()).strip()
            if text:
                return sigma_normalizetext(text)
    return sigma_normalizetext(''.join(rubric.itertext()).strip())

def gyatt_extractaudio(root):
    header_audio = ohiofindns(root, 'div', 'headerAudio')
    if header_audio is None:
        return ''
    data_author = header_audio.get('data-author', '') or ''
    try:
        audio_info = json.loads(html_module.unescape(data_author))
        return audio_info.get('mediaID', '')
    except Exception:
        m = re.search(r'"mediaID"\s*:\s*"([^"]+)"', data_author)
        return m.group(1) if m else ''

def skibidi_extractchoicetext(choice):
    text = ''.join(choice.itertext()).strip()
    if text:
        return sigma_normalizetext(text)
    for img in choice.iter():
        tag = img.tag.split('}')[-1] if '}' in img.tag else img.tag
        if tag == 'img':
            alt = img.get('alt', '') or ''
            if alt.strip():
                return sigma_normalizetext(alt)
    for media in choice.iter():
        tag = media.tag.split('}')[-1] if '}' in media.tag else media.tag
        if tag in ('audio', 'video'):
            for attr in ('alt', 'title', 'aria-label'):
                val = media.get(attr, '') or ''
                if val.strip():
                    return sigma_normalizetext(val)
    for attr in ('alt', 'title', 'aria-label'):
        val = choice.get(attr, '') or ''
        if val.strip():
            return sigma_normalizetext(val)
    return ''

def ohio_getresponsedecl(root, response_id):
    ns = skibidi_detectns(root)
    if ns:
        for rd in root.iter(f'{ns}responseDeclaration'):
            if (rd.get('identifier') or '').strip() == response_id:
                return rd
    for rd in root.iter('responseDeclaration'):
        if (rd.get('identifier') or '').strip() == response_id:
            return rd
    return None

def pom_getcorrectvalues(response_decl):
    if response_decl is None:
        return []
    values = []
    ns = skibidi_detectns(response_decl)
    if ns:
        cr = response_decl.find(f'.//{ns}correctResponse')
        if cr is not None:
            for v in cr.findall(f'.//{ns}value'):
                if v.text:
                    values.append(v.text.strip())
    if not values:
        cr = response_decl.find('.//correctResponse')
        if cr is not None:
            for v in cr.findall('.//value'):
                if v.text:
                    values.append(v.text.strip())
    return values

def rizz_parsemc(root, interactions, instruction, audio_filename):
    questions = []
    ns = skibidi_detectns(root)
    for i, interaction in enumerate(interactions, 1):
        answers = []
        correct_texts = []
        correct_ids = []

        choices = []
        if ns:
            choices = interaction.findall(f'.//{ns}simpleChoice')
        if not choices:
            choices = interaction.findall('.//simpleChoice')

        response_id = (interaction.get('responseIdentifier') or '').strip()
        response_decl = ohio_getresponsedecl(root, response_id)
        correct_ids = pom_getcorrectvalues(response_decl)

        if not correct_ids:
            for choice in choices:
                feedback = choice.get('answerfeedback', '') or ''
                if '#feedback:p1#' in feedback:
                    cid = (choice.get('identifier') or '').strip()
                    if cid:
                        correct_ids.append(cid)

        for choice in choices:
            choice_text = skibidi_extractchoicetext(choice)
            if not choice_text:
                continue
            answers.append(choice_text)
            choice_id = (choice.get('identifier') or '').strip()
            if choice_id in correct_ids:
                correct_texts.append(choice_text)

        if not correct_texts:
            for choice in choices:
                feedback = choice.get('answerfeedback', '') or ''
                if '#feedback:p1#' in feedback:
                    choice_text = skibidi_extractchoicetext(choice)
                    if choice_text:
                        correct_texts.append(choice_text)

        if answers:
            questions.append({
                'type': 'Multiple Choice',
                'question_number': i,
                'question': instruction or f'Question {i}',
                'instruction': instruction,
                'audio_filename': audio_filename,
                'answers': answers,
                'correct_answer': correct_texts[0] if correct_texts else '',
                'correct_answers': correct_texts,
                'is_multiple_answers': len(correct_texts) > 1,
                'correct_id': correct_ids[0] if correct_ids else '',
                'response_id': response_id,
            })
    return questions

def gyatt_getcontext(contentblock, interaction):
    if contentblock is None:
        return ''
    for paragraph in gyattfindallns(contentblock, 'p'):
        if not any(node is interaction for node in paragraph.iter()):
            continue

        def context_text(node):
            if node is interaction:
                return '[...]'
            parts = [node.text or '']
            for child in node:
                parts.append(context_text(child))
                parts.append(child.tail or '')
            return ''.join(parts)

        return sigma_normalizetext(context_text(paragraph))[:300]
    return ''


def ohio_parsedropdown(root, interactions, instruction, audio_filename):
    questions = []
    ns = skibidi_detectns(root)
    contentblock = ohiofindns(root, 'div', 'contentblock')

    for i, interaction in enumerate(interactions, 1):
        response_id = (interaction.get('responseIdentifier') or '').strip()

        options = []
        choice_els = []
        if ns:
            choice_els = interaction.findall(f'.//{ns}inlineChoice')
        if not choice_els:
            choice_els = interaction.findall('.//inlineChoice')

        for choice in choice_els:
            text = skibidi_extractchoicetext(choice)
            cid = (choice.get('identifier') or '').strip()
            if text:
                options.append((cid, text))

        correct_ids = pom_getcorrectvalues(ohio_getresponsedecl(root, response_id))
        correct_id = correct_ids[0] if correct_ids else ''
        correct_answer = ''
        for cid, text in options:
            if cid == correct_id:
                correct_answer = text
                break

        if not correct_answer:
            for choice in choice_els:
                feedback = choice.get('answerfeedback', '') or ''
                if '#feedback:p1' in feedback:
                    correct_answer = skibidi_extractchoicetext(choice)
                    correct_id = (choice.get('identifier') or '').strip()
                    break

        context = gyatt_getcontext(contentblock, interaction)

        questions.append({
            'type': 'Dropdown',
            'question_number': i,
            'question': context or instruction or f'Dropdown {i}',
            'instruction': instruction,
            'audio_filename': audio_filename,
            'answers': [t for _, t in options],
            'correct_answer': sigma_normalizetext(correct_answer),
            'correct_id': correct_id,
            'response_id': response_id,
        })
    return questions

def pom_parsetextentry(root, interactions, instruction, audio_filename):
    questions = []
    contentblock = ohiofindns(root, 'div', 'contentblock')
    for i, interaction in enumerate(interactions, 1):
        response_id = (interaction.get('responseIdentifier') or '').strip()
        accepted = pom_getcorrectvalues(ohio_getresponsedecl(root, response_id))
        accepted = [sigma_normalizetext(a) for a in accepted]
        context = gyatt_getcontext(contentblock, interaction)
        questions.append({
            'type': 'Text Entry',
            'question_number': i,
            'question': context or instruction or f'Gap {i}',
            'instruction': instruction,
            'audio_filename': audio_filename,
            'answers': accepted,
            'correct_answer': accepted[0] if accepted else '',
            'response_id': response_id,
        })
    return questions

def sigma_parsegapmatch(root, interactions, instruction, audio_filename):
    questions = []
    ns = skibidi_detectns(root)
    contentblock = ohiofindns(root, 'div', 'contentblock')
    for i, interaction in enumerate(interactions, 1):
        gap_texts = {}
        gap_els = []
        if ns:
            gap_els = interaction.findall(f'.//{ns}gapText')
        if not gap_els:
            gap_els = interaction.findall('.//gapText')

        for gt in gap_els:
            gt_id = (gt.get('identifier') or '').strip()
            gt_text = skibidi_extractchoicetext(gt)
            if gt_id and gt_text:
                gap_texts[gt_id] = gt_text

        correct_pairs = []
        for rd in root.iter():
            tag = rd.tag.split('}')[-1] if '}' in rd.tag else rd.tag
            if tag != 'responseDeclaration':
                continue
            for child in rd.iter():
                ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if ctag == 'correctResponse':
                    for v in child.iter():
                        vtag = v.tag.split('}')[-1] if '}' in v.tag else v.tag
                        if vtag == 'value' and v.text:
                            correct_pairs.append(v.text.strip())

        id_to_text = {}
        for pair in correct_pairs:
            parts = pair.split()
            if len(parts) == 2:
                gt_id, gap_id = parts
                if gt_id in gap_texts:
                    id_to_text[gap_id] = gap_texts[gt_id]

        context_parts = []
        if contentblock is not None:
            for p in contentblock.iter():
                tag = p.tag.split('}')[-1] if '}' in p.tag else p.tag
                if tag != 'p':
                    continue
                text = ''.join(p.itertext()).strip()
                if not text or text.startswith('#') or text.startswith('Correct!') or text.startswith('Incorrect!'):
                    continue
                context_parts.append(sigma_normalizetext(text))

        questions.append({
            'type': 'Drag & Drop',
            'question_number': i,
            'question': ' | '.join(context_parts) if context_parts else instruction,
            'instruction': instruction,
            'audio_filename': audio_filename,
            'answers': list(gap_texts.values()),
            'correct_answer': '',
            'correct_pairs': id_to_text,
            'gap_texts': gap_texts,
        })
    return questions

def skibidi_extractanswers(xml_content):
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        print(f"{Fore.RED}  XML parse error:{Style.RESET_ALL} {e}")
        return []

    instruction = rizz_extractrubric(root)
    audio_filename = gyatt_extractaudio(root)
    questions = []

    mc = gyattfindallns(root, 'choiceInteraction')
    if mc:
        questions.extend(rizz_parsemc(root, mc, instruction, audio_filename))

    dd = gyattfindallns(root, 'inlineChoiceInteraction')
    if dd:
        questions.extend(ohio_parsedropdown(root, dd, instruction, audio_filename))

    te = gyattfindallns(root, 'textEntryInteraction')
    if te:
        questions.extend(pom_parsetextentry(root, te, instruction, audio_filename))

    gm = gyattfindallns(root, 'gapMatchInteraction')
    if gm:
        questions.extend(sigma_parsegapmatch(root, gm, instruction, audio_filename))

    return questions

def gyatt_printquestions(xml_file, questions):
    print(f"\n{Fore.YELLOW}  {Path(xml_file).name}{Style.RESET_ALL} ({len(questions)} {t('printq_questions')})")

    for q in questions:
        qtype = q.get('type', '?')
        qnum = q.get('question_number', '?')
        print(f"\n  {Fore.CYAN}[Q{qnum}] [{qtype}]{Style.RESET_ALL}")
        ctx = q.get('question') or q.get('instruction') or ''
        if ctx:
            print(f"      {t('printq_context')}: {ctx}")

        audio = q.get('audio_filename', '')
        if audio:
            print(f"      {t('printq_audio')}: {audio}")

        if qtype == 'Drag & Drop':
            pairs = q.get('correct_pairs', {})
            options = q.get('answers', [])
            if options:
                print(f"      {t('printq_options')}: {', '.join(options)}")
            if pairs:
                for gap_id, answer in sorted(pairs.items()):
                    print(f"      {Fore.GREEN}{gap_id} -> {answer}{Style.RESET_ALL}")
            continue

        options = q.get('answers', [])
        if options and qtype != 'Text Entry':
            print(f"      {t('printq_options')}: {', '.join(options)}")

        correct = q.get('correct_answer', '')
        correct_all = q.get('correct_answers', [])
        if correct_all and len(correct_all) > 1:
            print(f"      {Fore.GREEN}{t('printq_correct')}: {', '.join(correct_all)}{Style.RESET_ALL}")
        elif correct:
            print(f"      {Fore.GREEN}{t('printq_correct')}: {correct}{Style.RESET_ALL}")
        else:
            correct_id = q.get('correct_id', '')
            if correct_id:
                print(f"      {Fore.YELLOW}{t('printq_correct_id')}: {correct_id} - {t('printq_not_found')}{Style.RESET_ALL}")

def skibidi_processxmlfiles(data, db=None, course=None, unit=None, exercise=None, lesson=None, source=None):
    processed_count = 0
    skipped_count = 0
    all_results = {}

    xml_files = sorted(name for name in data if name.endswith('.xml'))
    for index, filename in enumerate(xml_files, 1):
        print(f"  {Fore.CYAN}{t('xml_progress', n=index, total=len(xml_files), name=filename)}{Style.RESET_ALL}", flush=True)
        xml_content = data[filename]

        if sigma_isfinished(str(xml_content)):
            print(f"{Fore.YELLOW}  {t('summary_skip_finished', name=filename)}{Style.RESET_ALL}")
            skipped_count += 1
            continue

        decoded_xml = rizz_decodeunicode(xml_content)
        questions = skibidi_extractanswers(decoded_xml)
        if questions:
            gyatt_printquestions(filename, questions)
            all_results[filename] = questions
            processed_count += 1
        else:
            print(f"{Fore.YELLOW}  {t('summary_skip_noans', name=filename)}{Style.RESET_ALL}")
            skipped_count += 1

    print(f"\n  {t('summary')}: {Fore.GREEN}{processed_count} {t('summary_processed')}{Style.RESET_ALL}, "
          f"{Fore.RED}{skipped_count} {t('summary_skipped')}{Style.RESET_ALL}")

    if all_results and db and course and unit and exercise:
        if db.set(course, unit, exercise, all_results, lesson=lesson, source=source):
            print(f"  {Fore.GREEN}{t('summary_saved')}{Style.RESET_ALL}")
        else:
            print(f"  {Fore.RED}{t('summary_save_failed')}{Style.RESET_ALL}")

    return all_results

def pom_showdatabase(db):
    data = db.list_all()
    if not data:
        print(f"\n{Fore.YELLOW}  {t('db_empty')}{Style.RESET_ALL}")
        try:
            input(f"\n  {Fore.CYAN}{t('input_enter_back')}{Style.RESET_ALL}")
        except Exception:
            pass
        return

    print(f"\n{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  {t('db_header', n=len(data))}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")

    entries = list(data.items())
    for i, (key, entry) in enumerate(entries, 1):
        course = entry.get('course', '?')
        unit = entry.get('unit', '?')
        exercise = entry.get('exercise', '?')
        if entry.get('lesson'):
            exercise = f"{entry['lesson']} / {exercise}"
        saved_at = entry.get('saved_at', '')
        answers = entry.get('answers', {})
        xml_count = len(answers)

        print(f"\n  {Fore.WHITE}[{i}]{Style.RESET_ALL} {Fore.CYAN}{course} / {unit} / {exercise}{Style.RESET_ALL}")
        print(f"      {t('db_saved_at')}: {saved_at}")
        print(f"      {t('db_xml_count')}: {xml_count}")

    print(f"\n{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")

    try:
        choice = input(f"\n  {Fore.CYAN}{t('db_select_view')}{Style.RESET_ALL}").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(entries):
            entry = entries[idx][1]
            clear_screen()
            print(f"\n{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}  {entry.get('course')} / {entry.get('unit')} / {entry.get('exercise')}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}  {t('db_saved_at')}: {entry.get('saved_at', '')}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")

            if (entry.get('source') or {}).get('verification_version') != 1:
                print(f"  {Fore.YELLOW}{t('cached_legacy_warning')}{Style.RESET_ALL}")
            for xml_name, questions in entry.get('answers', {}).items():
                gyatt_printquestions(xml_name, questions)
        else:
            print(f"{Fore.RED}  {t('db_invalid_number')}{Style.RESET_ALL}")
    except ValueError:
        print(f"{Fore.RED}  {t('db_enter_number')}{Style.RESET_ALL}")

    try:
        input(f"\n  {Fore.CYAN}{t('input_enter_back')}{Style.RESET_ALL}")
    except Exception:
        pass

# Discovery deliberately reads textContent, not visibility or viewport layout.
# Cambridge can hide/offload earlier lessons while the user is at Lesson D.
# Visibility is checked only when choosing an element to interact with.
WORKBOOK_DOM_HELPERS = r'''
    const norm = value => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const textOf = el => el ? (el.textContent || '').trim() : '';
    const visible = el => !!el && !!el.getClientRects().length &&
        getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
    const headingSelector = '.unit-info .h5, .unit-detail .h5, .unit-info h5, .unit-detail h5, .card-header .h5, .card-header h5, [class*="unit-title"]';
    const findUnit = name => {
        const wanted = norm(name);
        // Prefer a card's OWN heading, never a product card containing many units.
        for (const heading of document.querySelectorAll(headingSelector)) {
            if (norm(textOf(heading)) !== wanted) continue;
            const card = heading.closest('.card');
            if (card) {
                card.setAttribute('data-cambridge-extractor-unit-root', wanted);
                return card;
            }
            const detail = heading.closest('.unit-detail, [class*="unit-title"]');
            if (detail && detail.parentElement) {
                detail.parentElement.setAttribute('data-cambridge-extractor-unit-root', wanted);
                return detail.parentElement;
            }
        }
        for (const heading of document.querySelectorAll('.h5, h5, .unit-detail, [class*="unit-title"]')) {
            if (norm(textOf(heading)) !== wanted) continue;
            const card = heading.closest('.card');
            if (card) {
                card.setAttribute('data-cambridge-extractor-unit-root', wanted);
                return card;
            }
        }
        // A virtual scroller can temporarily unmount a heading. Only reuse a
        // previously identified unit root, and reject it if recycled for another unit.
        for (const root of document.querySelectorAll('[data-cambridge-extractor-unit-root]')) {
            if (root.getAttribute('data-cambridge-extractor-unit-root') !== wanted) continue;
            const own = Array.from(root.querySelectorAll(headingSelector)).filter(el => !el.closest('.card') || el.closest('.card') === root);
            if (!own.length || own.some(el => norm(textOf(el)) === wanted)) return root;
        }
        return null;
    };
    const unitToggle = unit => unit && unit.querySelector('.unit-detail, .card-header, [aria-expanded], button, a, h5');
    const unitOpen = unit => {
        if (!unit) return false;
        const toggle = unitToggle(unit);
        if (toggle && toggle.getAttribute('aria-expanded') === 'false') return false;
        if (toggle && toggle.getAttribute('aria-expanded') === 'true') return true;
        const collapse = unit.querySelector('.collapse, .collapsing');
        if (collapse) return collapse.classList.contains('show') || collapse.classList.contains('in');
        return unit.getAttribute('data-cambridge-extractor-expanded') === 'true' ||
            Array.from(unit.querySelectorAll('.activity-info, [class*="activity"], a[href*="/view/"]')).some(visible);
    };
'''

EXERCISES_DOM_SCRIPT = '(unitName) => {' + WORKBOOK_DOM_HELPERS + r'''
    const result = {unit_name: unitName, lessons: [], discovery: {root_found: false, lesson_headers: [], busy: false}};
    const unit = findUnit(unitName);
    if (!unit) return result;
    result.discovery.root_found = true;
    // An in-progress exercise can have a permanent ring/spinner. It is not
    // evidence that the UNIT is still loading. Only use content-level signals.
    result.discovery.busy = unit.getAttribute('aria-busy') === 'true' ||
        Array.from(unit.querySelectorAll('[aria-busy="true"], .lessons-loading, .activities-loading, .workbook-loading')).some(el =>
            visible(el) && !el.closest('.activity-info, .activity-row, .activity-item, .activity-status, a[href*="/view/"]'));
    let currentLesson = null;
    const invalidNames = new Set(['completed', 'in progress', 'not started', 'in-progress', 'not-started']);
    const rowOf = node => {
        const row = node.closest('a, button, [role="button"], .activity-row, .activity-item, [data-activity-id]');
        if (row && unit.contains(row)) return row;
        const parent = node.parentElement;
        if (node.matches('.activity-info') && parent && parent !== unit && parent.querySelectorAll('.activity-info').length === 1) return parent;
        return node;
    };
    const statusOf = node => {
        const row = rowOf(node);
        const markup = (row.innerHTML + ' ' + row.className + ' ' +
            (row.getAttribute('aria-label') || '') + ' ' + (row.getAttribute('data-status') || '')).toLowerCase();
        if (/not[-_ ]started|(?:^|[\s"'_-])pending(?:[\s"'<>_-]|$)/.test(markup)) return 'pending';
        if (/nemo-tick|green-tick|(?:^|[\s"'_-])completed(?:[\s"'<>_-]|$)/.test(markup)) return 'completed';
        if (/inprogress|in[-_ ]progress|nemo-progress/.test(markup)) return 'in-progress';
        return 'pending';
    };
    const activityName = node => {
        const title = node.querySelector('.activity-name, .activity-title, [class*="activity-name"], [class*="activity-title"]');
        if (title && !title.querySelector('.activity-info')) return textOf(title);
        // Block descendants keep the name separate from status labels even
        // when a hidden element's innerText falls back to concatenated text.
        const first = Array.from(node.querySelectorAll('p, span')).find(el => {
            const value = norm(textOf(el));
            return value.length >= 2 && /[\p{L}\p{N}]/u.test(value) && !invalidNames.has(value) &&
                !el.matches('[class*="icon"], [class*="tick"]') && !el.closest('svg, .star, .nemo-tick, .green-tick');
        });
        if (first) return textOf(first);
        return (node.innerText || textOf(node)).split('\n').map(line => line.trim()).find(Boolean) || '';
    };
    const addActivity = node => {
        // Never mistake a container of several rows for its first exercise.
        if (node.querySelector('.activity-info')) return;
        if (node.matches('.loading, .spinner, [class*="loading"], [class*="skeleton"], [class*="placeholder"]')) return;
        if (!node.matches('.activity-info') && node.matches('[class*="status"], [class*="star"], [class*="icon"], [class*="tick"]')) return;
        const name = activityName(node);
        if (!name || name.length < 2 || /^Lesson\s+[A-Z]/i.test(name) ||
            invalidNames.has(norm(name)) || norm(name) === norm(unitName) || /^\d+\s+/.test(name)) return;
        const exact = Array.from(node.querySelectorAll('*')).filter(el => norm(textOf(el)) === norm(name));
        const target = exact.length ? exact[exact.length - 1] : node;
        const row = rowOf(node);
        const link = target.closest('a[href]');
        const rawHref = link && link.getAttribute('href');
        const href = rawHref && !rawHref.startsWith('#') && !rawHref.startsWith('javascript:') ? link.href : null;
        const activity_id = row.getAttribute('data-activity-id') || row.getAttribute('data-item-id') || null;
        if (!currentLesson) {
            currentLesson = {name: 'Exercises', exercises: []};
            result.lessons.push(currentLesson);
        }
        const priority = node.matches('.activity-info') ? 3 : node.matches('a, button, [role="button"]') ? 2 : 1;
        const previous = currentLesson.exercises.find(ex => norm(ex.name) === norm(name) &&
            ((href && href === ex.href) || (activity_id && activity_id === ex.activity_id) ||
             (!href && !ex.href && !activity_id && !ex.activity_id) ||
             ex.targets.some(el => el.contains(target) || target.contains(el))));
        if (previous) {
            if (!previous.targets.includes(target)) previous.targets.push(target);
            if (priority >= previous.priority) {
                previous.status = statusOf(node);
                previous.priority = priority;
                previous.href = href;
                previous.activity_id = activity_id;
            }
        } else {
            currentLesson.exercises.push({name, status: statusOf(node), href, activity_id, targets: [target], priority});
        }
    };
    for (const node of unit.querySelectorAll('*')) {
        // DO NOT filter hidden/offscreen nodes here: this is a full catalog,
        // not a list of what happens to be painted at the current scroll position.
        if (node.closest('script, style, template, noscript')) continue;
        const text = norm(textOf(node));
        if (/^lesson\s+[a-z]$/i.test(text)) {
            currentLesson = result.lessons.find(lesson => norm(lesson.name) === text);
            if (!currentLesson) {
                currentLesson = {name: textOf(node).replace(/\s+/g, ' '), exercises: []};
                result.lessons.push(currentLesson);
            }
            if (!result.discovery.lesson_headers.some(name => norm(name) === text)) result.discovery.lesson_headers.push(currentLesson.name);
            continue;
        }
        if (node.matches('.activity-info, [class*="activity"]') ||
            (node.matches('a') && node.querySelector('.star, [class*="star"], i, img'))) addActivity(node);
    }
    if (result.lessons.every(lesson => !lesson.exercises.length)) {
        // Preserve observed lesson headers, including not-yet-loaded ones.
        currentLesson = null;
        for (const node of unit.querySelectorAll('a, button, [role="button"]')) {
            if (!node.closest('.card-header, .unit-detail')) addActivity(node);
        }
    }
    document.querySelectorAll('[data-cambridge-extractor-activity]').forEach(el => el.removeAttribute('data-cambridge-extractor-activity'));
    let index = 0;
    for (const lesson of result.lessons) {
        lesson.exercises = lesson.exercises.map(ex => {
            const dom_id = String(index++);
            for (const target of ex.targets) target.setAttribute('data-cambridge-extractor-activity', dom_id);
            return {name: ex.name, status: ex.status, href: ex.href, activity_id: ex.activity_id, dom_id};
        });
    }
    return result;
}'''

# Walk the selected unit (not the whole course), including a scrollable workbook
# panel or virtual-list viewport. The extent is recalculated as lazy content grows.
UNIT_SCROLL_SCRIPT = '(options) => {' + WORKBOOK_DOM_HELPERS + r'''
    if (options.action === 'restore') {
        const root = document.querySelector('[data-cambridge-extractor-scroll-root="selected"]');
        if (root) root.scrollTo({top: options.position, behavior: 'instant'});
        return null;
    }
    const unit = findUnit(options.unit);
    if (!unit) return {found: false, at_end: true};
    const scrolling = document.scrollingElement;
    const scrollable = el => el && el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 4 &&
        /auto|scroll/.test(getComputedStyle(el).overflowY);
    let root = Array.from(unit.querySelectorAll('cdk-virtual-scroll-viewport, [class*="virtual-scroll"], [data-virtual-scroll]')).find(scrollable);
    if (!root) {
        for (let el = unit; el && el !== document.body; el = el.parentElement) {
            if (scrollable(el)) { root = el; break; }
        }
    }
    root = root || scrolling;
    document.querySelectorAll('[data-cambridge-extractor-scroll-root]').forEach(el => el.removeAttribute('data-cambridge-extractor-scroll-root'));
    root.setAttribute('data-cambridge-extractor-scroll-root', 'selected');
    const original = root.scrollTop;
    const height = root === scrolling ? window.innerHeight : root.clientHeight;
    const viewportTop = root === scrolling ? 0 : root.getBoundingClientRect().top;
    const rect = unit.getBoundingClientRect();
    const inner = root === unit || unit.contains(root);
    const start = inner ? 0 : Math.max(0, original + rect.top - viewportTop - 24);
    const end = inner ? root.scrollHeight - height : Math.min(root.scrollHeight - height, original + rect.bottom - viewportTop - height + 24);
    const target = options.action === 'begin' ? start : Math.min(Math.max(start, end), original + Math.max(120, height * 0.65));
    root.scrollTo({top: target, behavior: 'instant'});
    return {found: true, position: root.scrollTop, original, at_end: root.scrollTop >= Math.max(start, end) - 2};
}'''

ACTIVITY_STATE_SCRIPT = r'''() => {
    const norm = value => (value || '').replace(/\s+/g, ' ').trim();
    const visible = el => !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
    const primary = Array.from(document.querySelectorAll(
        '.activity-title, [class*="activity-title"], [class*="activityTitle"], [class*="item-title"], [class*="itemTitle"], [class*="player-title"]'
    )).filter(visible).map(el => norm(el.textContent)).filter(Boolean);
    const headers = Array.from(document.querySelectorAll(
        'header h1, header span, nav h1, nav span, .navbar .title, .activity-header .title, .product-title, h1'
    )).filter(visible).map(el => norm(el.textContent)).filter(Boolean);
    const tabTitle = norm(document.title.split('|')[0]);
    const brandedTab = /\|\s*Cambridge One\s*$/i.test(document.title) && !/^Cambridge One$/i.test(tabTitle) ? tabTitle : '';
    const title = primary[0] || brandedTab || headers.find(text => text.toLowerCase() === tabTitle.toLowerCase()) ||
        headers.find(text => !/cambridge/i.test(text)) || tabTitle;
    return {title, url: location.href, in_exercise: /\/(?:view|activity|item)(?:\/|$)/i.test(location.pathname)};
}'''

VERIFY_ACTIVITY_SCRIPT = r'''expected => {
    const state = (''' + ACTIVITY_STATE_SCRIPT + r''')();
    const norm = value => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    if (!state.in_exercise || norm(state.title) !== norm(expected.name)) return false;
    if (expected.href) {
        const actualUrl = new URL(state.url);
        const expectedUrl = new URL(expected.href, location.href);
        const path = url => decodeURIComponent(url.pathname).replace(/\/+$/, '');
        if (actualUrl.origin !== expectedUrl.origin || path(actualUrl) !== path(expectedUrl)) return false;
        for (const key of new Set(expectedUrl.searchParams.keys())) {
            if (actualUrl.searchParams.getAll(key).sort().join('\0') !== expectedUrl.searchParams.getAll(key).sort().join('\0')) return false;
        }
        if (expectedUrl.hash && actualUrl.hash !== expectedUrl.hash) return false;
    }
    return state;
}'''


class CambridgeOneScraper:
    WINDOW_POSITION = "0,0"
    WINDOW_SIZE = "1680,1050"
    WORKBOOK_SELECTOR = '.unit-detail, .unit-info, [class*="unit-title"]'
    PROGRESS_INTERVAL = 3

    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.configs_dir = Path("configs")
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_file = self.configs_dir / "cambridge_accounts.json"
        self.profiles_dir = Path("chrome_data")
        self.active_account = None
        self.playwright = None
        self.data_js_urls = []
        self.data_js_contents = {}
        self.last_data_js_url = None
        self.workbook_url = None
        self.current_unit = None
        self.verified_exercise = None
        self._data_js_generation = 0
        self._tracking_data_js = False
        self._data_js_requests = {}
        self._data_js_tasks = set()
        self._exercise_catalogs = {}
        self._last_scan_reached_end = False

    def _account_key(self, email):
        return hashlib.sha256(email.strip().lower().encode('utf-8')).hexdigest()[:20]

    def _profile_dir(self, email):
        return self.profiles_dir / self._account_key(email)

    def load_accounts(self):
        try:
            if self.accounts_file.exists():
                with open(self.accounts_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
        return []

    def save_account(self, email, password=None):
        email = email.strip()
        if not email:
            return False
        accounts = self.load_accounts()
        key = self._account_key(email)
        existing = next((a for a in accounts if a.get('key') == key), None)
        entry = {'key': key, 'email': email}
        if password:
            entry['password'] = password
        elif existing and existing.get('password'):
            entry['password'] = existing['password']
        accounts = [a for a in accounts if a.get('key') != key]
        accounts.insert(0, entry)
        try:
            with open(self.accounts_file, 'w', encoding='utf-8') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def delete_account_password(self, email):
        accounts = self.load_accounts()
        key = self._account_key(email)
        for a in accounts:
            if a.get('key') == key:
                a.pop('password', None)
        try:
            with open(self.accounts_file, 'w', encoding='utf-8') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    async def debug_wait(self, seconds=0.5):
        await asyncio.sleep(seconds)

    async def safe_wait_for_load(self, timeout=8000):
        try:
            await self.page.wait_for_load_state('domcontentloaded', timeout=timeout)
            await self.page.wait_for_load_state('networkidle', timeout=timeout)
        except Exception:
            pass

    async def wait_for_loading_spinner(self, timeout=15):
        try:
            await self.page.wait_for_selector(
                '.loading, .spinner, [class*="spinner"], [class*="loading"]',
                state='detached', timeout=timeout * 1000
            )
        except Exception:
            pass

    def reset_data_js_tracking(self):
        self._tracking_data_js = False
        self._data_js_generation += 1
        for task in list(self._data_js_tasks):
            task.cancel()
        self._data_js_requests.clear()
        self.data_js_urls.clear()
        self.data_js_contents.clear()
        self.last_data_js_url = None
        self.verified_exercise = None

    async def init_browser(self, profile_dir=None, headless=False):
        self.playwright = await async_playwright().start()
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = Path(profile_dir or (self.profiles_dir / "default"))
        profile_dir.mkdir(parents=True, exist_ok=True)

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir.resolve()),
            headless=headless,
            viewport=None,
            args=[
                f'--window-position={self.WINDOW_POSITION}',
                f'--window-size={self.WINDOW_SIZE}',
            ]
        )
        self.browser = self.context.browser
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.on("request", self._on_request)
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._on_response)

    @staticmethod
    def _is_data_js_url(url):
        return urlsplit(url).path.rsplit('/', 1)[-1].lower() == 'data.js'

    def _on_request(self, request):
        if self._tracking_data_js and self._is_data_js_url(request.url):
            self._data_js_requests[request] = self._data_js_generation

    def _on_request_failed(self, request):
        self._data_js_requests.pop(request, None)

    def _on_response(self, response):
        if not self._is_data_js_url(response.url):
            return
        generation = self._data_js_requests.pop(response.request, None)
        if not self._tracking_data_js or generation != self._data_js_generation:
            return
        if not response.ok:
            print(f"  {Fore.YELLOW}{t('datajs_http_failed', status=response.status)}{Style.RESET_ALL}", flush=True)
            return
        url = response.url
        if url not in self.data_js_urls:
            self.data_js_urls.append(url)
        self.last_data_js_url = url
        task = asyncio.create_task(self._fetch_data_js_content(url, response, generation))
        self._data_js_tasks.add(task)
        task.add_done_callback(self._data_js_tasks.discard)

    async def _fetch_data_js_content(self, url, response, generation):
        try:
            body = await response.body()
            if generation != self._data_js_generation or not self._tracking_data_js:
                return
            self.data_js_contents[url] = body.decode('utf-8', errors='replace')
            print(f"  {Fore.GREEN}{t('datajs_received', size=len(body))}{Style.RESET_ALL}", flush=True)
        except PlaywrightError as error:
            if generation == self._data_js_generation and self._tracking_data_js:
                print(f"  {Fore.YELLOW}{t('datajs_read_failed', error=type(error).__name__)}{Style.RESET_ALL}", flush=True)

    async def _wait_for_data_js(self, timeout=25):
        print(f"  {Fore.CYAN}{t('datajs_fetching')}{Style.RESET_ALL}", flush=True)
        started = time.monotonic()
        last_report = started
        generation = self._data_js_generation
        while time.monotonic() - started < timeout:
            if generation != self._data_js_generation:
                return False
            if self.data_js_urls and all(url in self.data_js_contents for url in self.data_js_urls):
                return True
            now = time.monotonic()
            if now - last_report >= self.PROGRESS_INTERVAL:
                print(f"  {Fore.CYAN}{t('datajs_waiting', received=len(self.data_js_contents), total=len(self.data_js_urls), seconds=now - started)}{Style.RESET_ALL}", flush=True)
                last_report = now
            await asyncio.sleep(min(0.2, self.PROGRESS_INTERVAL, max(0, timeout - (time.monotonic() - started))))
        # A captured URL can still be retried asynchronously with the browser's cookies.
        return bool(self.data_js_urls)

    async def check_login_status(self):
        print(f"  {Fore.CYAN}{t('login_checking_session')}{Style.RESET_ALL}")
        try:
            await self.page.goto('https://www.cambridgeone.org/dashboard/learner/dashboard',
                                 wait_until='domcontentloaded', timeout=20000)
        except Exception:
            pass
        await self.debug_wait(2)
        try:
            await self.page.wait_for_load_state('networkidle', timeout=6000)
        except Exception:
            pass

        current_url = self.page.url.lower()
        print(f"  {Fore.CYAN}{t('login_current_url', url=current_url)}{Style.RESET_ALL}")

        if '/login' in current_url:
            return False
        try:
            login_form = await self.page.query_selector('input[type="password"], input[name="password"]')
            if login_form and await login_form.is_visible():
                return False
        except Exception:
            pass

        if 'dashboard' in current_url or '/learner/' in current_url:
            return True
        return False

    async def login(self, email, password):
        print(f"\n  {Fore.CYAN}{t('login_logging_in')}{Style.RESET_ALL}")
        await self.page.goto('https://www.cambridgeone.org/login')
        await self.safe_wait_for_load()
        await self.debug_wait(1)

        email_selectors = [
            'input[type="text"][name="username"]', 'input[type="text"][name="loginID"]',
            'input[type="email"]', 'input.gigya-input-text', 'input[data-gigya-name="loginID"]',
            'input[id*="loginID"]', 'input[id*="login"]', 'input[placeholder*="username"]',
            'input[placeholder*="email"]',
        ]
        email_field = None
        for sel in email_selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    email_field = el
                    break
            except Exception:
                continue
        if not email_field:
            print(f"  {Fore.RED}[-] Could not find email field{Style.RESET_ALL}")
            return False

        await email_field.click()
        await email_field.fill('')
        await email_field.type(email, delay=20)
        await email_field.press('Tab')
        await self.debug_wait(0.5)

        pw_selectors = [
            'input[type="password"]', 'input.gigya-input-password',
            'input[id*="password"]', 'input[name="password"]',
        ]
        pw_field = None
        for sel in pw_selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    pw_field = el
                    break
            except Exception:
                continue
        if not pw_field:
            print(f"  {Fore.RED}[-] Could not find password field{Style.RESET_ALL}")
            return False

        await pw_field.click()
        await pw_field.fill('')
        await pw_field.type(password, delay=20)
        await pw_field.press('Enter')
        await self.debug_wait(3)

        try:
            await self.page.wait_for_load_state('networkidle', timeout=10000)
        except Exception:
            pass

        current_url = self.page.url
        if 'dashboard' in current_url or 'home' in current_url or 'classes' in current_url:
            print(f"  {Fore.GREEN}{t('login_success')}{Style.RESET_ALL}")
            return True
        try:
            page_text = await self.page.inner_text('body')
            if 'Active classes' in page_text or 'My classes' in page_text:
                print(f"  {Fore.GREEN}{t('login_success')}{Style.RESET_ALL}")
                return True
        except Exception:
            pass
        print(f"  {Fore.RED}{t('login_failed')}{Style.RESET_ALL}")
        return False

    async def get_courses_with_workbooks(self):
        print(f"\n  {Fore.CYAN}{t('courses_fetching')}{Style.RESET_ALL}")
        current_url = self.page.url
        if 'dashboard' not in current_url:
            await self.page.goto('https://www.cambridgeone.org/dashboard/learner/dashboard')
            await self.safe_wait_for_load()
            await self.debug_wait(1)

        try:
            await self.page.wait_for_selector('.umbrella-tile', timeout=12000)
        except Exception:
            pass

        courses_data = await self._evaluate_read('''
            () => {
                const courses = [];
                const tiles = document.querySelectorAll('.umbrella-tile');
                tiles.forEach(tile => {
                    const link = tile.querySelector('a.tile-section-link');
                    if (!link) return;
                    const ariaLabel = link.getAttribute('aria-label') || '';
                    if (!ariaLabel.includes('Digital Workbook')) return;
                    const nameElem = tile.querySelector('.my-progress');
                    const workbookName = nameElem ? nameElem.innerText.trim() : '';
                    let courseName = '';
                    const match = ariaLabel.match(/for\\s+([^\\-]+?)(?:\\s*[–-]|$)/);
                    if (match) courseName = match[1].trim();
                    else {
                        const allText = tile.innerText || '';
                        const lines = allText.split('\\n').filter(line => line.trim());
                        for (const line of lines) {
                            if (line.includes('Four Corners') || line.includes('Cambridge')) {
                                courseName = line.trim();
                                break;
                            }
                        }
                    }
                    if (!courseName) {
                        const parts = ariaLabel.split(' for ');
                        if (parts.length > 1) courseName = parts[1].trim();
                    }
                    if (workbookName && courseName) courses.push({ courseName, workbookName });
                });
                return courses;
            }
        ''')
        print(f"  {Fore.GREEN}{t('courses_found', n=len(courses_data))}{Style.RESET_ALL}")
        return courses_data

    async def click_workbook(self, course_name):
        print(f"  {Fore.CYAN}{t('courses_opening', name=course_name)}{Style.RESET_ALL}")
        result = await self.page.evaluate('''
            (courseName) => {
                const tiles = document.querySelectorAll('.umbrella-tile');
                for (const tile of tiles) {
                    const link = tile.querySelector('a.tile-section-link');
                    if (!link) continue;
                    const ariaLabel = link.getAttribute('aria-label') || '';
                    if (!ariaLabel.includes('Digital Workbook')) continue;
                    if (ariaLabel.includes(courseName)) { link.click(); return true; }
                    const text = tile.innerText || '';
                    if (text.includes(courseName)) { link.click(); return true; }
                }
                return false;
            }
        ''', course_name)
        if result:
            print(f"  {Fore.GREEN}{t('courses_opened')}{Style.RESET_ALL}")
            await self.safe_wait_for_load()
            await self.wait_for_loading_spinner(timeout=10)
            try:
                await self.page.locator(self.WORKBOOK_SELECTOR).first.wait_for(state='visible', timeout=20000)
            except PlaywrightError:
                print(f"  {Fore.RED}{t('courses_open_failed')}{Style.RESET_ALL}")
                return False
            self.workbook_url = self.page.url
            self.current_unit = None
            return True
        print(f"  {Fore.RED}{t('courses_open_failed')}{Style.RESET_ALL}")
        return False

    async def get_all_units(self):
        if self.workbook_url and not await self.return_to_workbook():
            return []
        print(f"\n  {Fore.CYAN}{t('units_loading')}{Style.RESET_ALL}")
        for _ in range(4):
            try:
                await self.wait_for_loading_spinner(timeout=8)
                await self.page.wait_for_selector('.card, .unit-detail, [class*="unit"]', timeout=5000)
                break
            except Exception:
                await asyncio.sleep(2)

        units_data = []
        for _ in range(3):
            units_data = await self._evaluate_read('''
                () => {
                    const units = [];
                    const cards = document.querySelectorAll('.card');
                    cards.forEach((card) => {
                        let unitName = '';
                        const h5 = card.querySelector('.unit-info .h5');
                        if (h5) unitName = h5.innerText.trim();
                        if (!unitName) {
                            const h5_2 = card.querySelector('.unit-detail .h5');
                            if (h5_2) unitName = h5_2.innerText.trim();
                        }
                        if (!unitName) {
                            const lines = (card.innerText || '').split('\\n').filter(l => l.trim());
                            for (const line of lines) {
                                if (line.match(/^\\d+\\s+\\w+/)) { unitName = line.trim(); break; }
                            }
                        }
                        if (unitName) units.push({ name: unitName });
                    });
                    if (units.length === 0) {
                        document.querySelectorAll('.unit-detail, [class*="unit-title"]').forEach(detail => {
                            const h5 = detail.querySelector('.h5, h5, .title');
                            if (h5) {
                                const name = h5.innerText.trim();
                                if (name) units.push({ name });
                            }
                        });
                    }
                    return units;
                }
            ''')
            if units_data:
                break
            await asyncio.sleep(2)
        if units_data and not self._is_exercise_url(self.page.url):
            self.workbook_url = self.page.url
        print(f"  {Fore.GREEN}{t('units_found', n=len(units_data))}{Style.RESET_ALL}")
        return units_data

    @staticmethod
    def _is_exercise_url(url):
        return bool(re.search(r'/(?:view|activity|item)(?:/|$)', urlsplit(url).path, re.I))

    @staticmethod
    def _is_navigation_error(error):
        message = str(error).lower()
        return any(text in message for text in (
            'execution context was destroyed', 'cannot find context with specified id',
            'most likely because of a navigation',
        ))

    async def _evaluate_read(self, script, arg=None):
        # Retry only idempotent DOM reads, never arbitrary clicks/toggles.
        for attempt in range(3):
            try:
                return await self.page.evaluate(script, arg)
            except PlaywrightError as error:
                if not self._is_navigation_error(error) or attempt == 2:
                    raise
                print(f"  {Fore.CYAN}{t('navigation_retry', n=attempt + 1)}{Style.RESET_ALL}", flush=True)
                with suppress(PlaywrightError):
                    await self.page.wait_for_load_state('domcontentloaded', timeout=5000)
                await asyncio.sleep(0.2)

    async def return_to_workbook(self, unit_name=None):
        """Restore the captured workbook URL, not the player's internal history."""
        try:
            if not self.workbook_url:
                if self._is_exercise_url(self.page.url):
                    raise ValueError('Workbook URL is unknown')
                self.workbook_url = self.page.url
            navigating = self.page.url.rstrip('/') != self.workbook_url.rstrip('/')
            if navigating:
                print(f"  {Fore.CYAN}{t('exercises_back_workbook')}{Style.RESET_ALL}", flush=True)
            self._tracking_data_js = False
            async with report_progress('stage_return_workbook'):
                if navigating:
                    await self.page.goto(self.workbook_url, wait_until='domcontentloaded', timeout=20000)
                await self.page.locator(self.WORKBOOK_SELECTOR).first.wait_for(state='visible', timeout=15000)
                if unit_name and not await self.click_unit(unit_name, announce=False):
                    raise ValueError('Unit is not available in the Workbook')
            self.verified_exercise = None
            if navigating:
                print(f"  {Fore.GREEN}{t('exercises_returned')}{Style.RESET_ALL}", flush=True)
            return True
        except (PlaywrightError, ValueError) as error:
            print(f"  {Fore.RED}{t('exercises_return_failed')}{Style.RESET_ALL}", flush=True)
            print(f"  {Fore.YELLOW}{type(error).__name__}: {error}{Style.RESET_ALL}")
            return False

    async def click_unit(self, unit_name, announce=True):
        if announce:
            print(f"  {Fore.CYAN}{t('units_opening', name=unit_name)}{Style.RESET_ALL}", flush=True)
        script = '(unitName) => {' + WORKBOOK_DOM_HELPERS + r'''
            const unit = findUnit(unitName);
            if (!unit) return 'missing';
            if (unitOpen(unit)) return 'open';
            const toggle = unitToggle(unit);
            if (!toggle) return 'missing';
            document.querySelectorAll('[data-cambridge-extractor-unit]').forEach(el => el.removeAttribute('data-cambridge-extractor-unit'));
            toggle.setAttribute('data-cambridge-extractor-unit', 'selected');
            return 'click';
        }'''
        try:
            state = await self._evaluate_read(script, unit_name)
            if state == 'missing':
                print(f"  {Fore.RED}{t('units_open_failed')}{Style.RESET_ALL}")
                return False
            if state == 'click':
                toggle = self.page.locator('[data-cambridge-extractor-unit="selected"]')
                await toggle.scroll_into_view_if_needed(timeout=5000)
                await toggle.click(timeout=10000)
                await self._evaluate_read(
                    '(unitName) => {' + WORKBOOK_DOM_HELPERS + "const unit = findUnit(unitName); if (unit) unit.setAttribute('data-cambridge-extractor-expanded', 'true');}",
                    unit_name,
                )
                handle = await self.page.wait_for_function(
                    '(unitName) => {' + WORKBOOK_DOM_HELPERS + 'return unitOpen(findUnit(unitName));}',
                    arg=unit_name, timeout=15000,
                )
                await handle.dispose()
            self.current_unit = unit_name
            if announce:
                print(f"  {Fore.GREEN}{t('units_opened')}{Style.RESET_ALL}")
            return True
        except PlaywrightError as error:
            print(f"  {Fore.RED}{t('units_open_failed')}{Style.RESET_ALL} ({error})")
            return False

    async def _scan_unit_snapshots(self, unit_name, deadline):
        """Visit the whole unit, including lazy/virtual sections, without opening activities."""
        state = await self._evaluate_read(UNIT_SCROLL_SCRIPT, {'unit': unit_name, 'action': 'begin'})
        while state.get('found') and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            yield await self._evaluate_read(EXERCISES_DOM_SCRIPT, unit_name)
            if state['at_end']:
                break
            state = await self._evaluate_read(UNIT_SCROLL_SCRIPT, {'unit': unit_name, 'action': 'advance'})
        self._last_scan_reached_end = bool(state.get('found') and state.get('at_end'))

    async def get_exercises_in_unit(self, unit_name, timeout=30, announce=True):
        if announce:
            print(f"\n  {Fore.CYAN}{t('units_exercises_fetching', name=unit_name)}{Style.RESET_ALL}", flush=True)
        deadline = time.monotonic() + timeout
        key = (self.workbook_url, normalized_name(unit_name))
        previous = self._exercise_catalogs.get(key)
        data = {'unit_name': unit_name, 'lessons': [], 'discovery': {}}
        last_signature = None
        stable_passes = 0
        complete = False
        try:
            async with report_progress('stage_exercises'):
                while time.monotonic() < deadline:
                    self._last_scan_reached_end = False
                    pass_data = {'unit_name': unit_name, 'lessons': [], 'discovery': {}}
                    async for snapshot in self._scan_unit_snapshots(unit_name, deadline):
                        pass_data = merge_exercise_catalogs(pass_data, snapshot)
                    # Union positions WITHIN a pass, but compare fresh whole
                    # passes so transient loading rows cannot live forever.
                    data = pass_data if self._last_scan_reached_end else merge_exercise_catalogs(data, pass_data)
                    signature = catalog_signature(data)
                    if announce and signature != last_signature:
                        count = sum(len(lesson['exercises']) for lesson in data['lessons'])
                        print(f"  {Fore.CYAN}{t('exercises_scan_progress', lessons=len(data['lessons']), exercises=count)}{Style.RESET_ALL}", flush=True)
                    stable_passes = stable_passes + 1 if signature == last_signature else 1
                    last_signature = signature
                    missing_previous = set(catalog_signature(previous or {})) - set(signature)
                    discovery = data['discovery']
                    complete = bool(
                        signature and self._last_scan_reached_end and stable_passes >= 2
                        and discovery.get('root_found') and not discovery.get('busy')
                        and not discovery.get('missing_lessons') and not missing_previous
                    )
                    if complete:
                        break
                    await asyncio.sleep(0.3)
        finally:
            # Leave the browser at the START of the selected unit, not at D or
            # in the next unit. This also wakes the first virtualized lesson.
            with suppress(PlaywrightError):
                await self._evaluate_read(UNIT_SCROLL_SCRIPT, {'unit': unit_name, 'action': 'begin'})
        missing_previous = set(catalog_signature(previous or {})) - set(catalog_signature(data))
        if missing_previous:
            data = merge_exercise_catalogs(previous, data)
        data['discovery'].update(
            complete=complete, stable_passes=stable_passes,
            previous_entries_not_seen=len(missing_previous),
        )
        # Never replace a known complete catalog with a partial scan, or
        # promote a transient/timeout snapshot into a trusted baseline.
        if complete:
            self._exercise_catalogs[key] = data
        self.current_unit = unit_name
        if announce:
            count = sum(len(lesson['exercises']) for lesson in data['lessons'])
            print(f"  {Fore.GREEN if complete else Fore.YELLOW}{t('exercises_catalog_summary', lessons=len(data['lessons']), exercises=count)}{Style.RESET_ALL}", flush=True)
        return data

    async def _locate_exercise(self, unit_name, exercise_name, lesson_name, href=None, timeout=20):
        """Find a CURRENT clickable target, not a marker from a previous snapshot."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._last_scan_reached_end = False
            async for snapshot in self._scan_unit_snapshots(unit_name, deadline):
                matches = [
                    exercise for lesson in snapshot['lessons'] for exercise in lesson['exercises']
                    if normalized_name(exercise['name']) == normalized_name(exercise_name)
                    and (not lesson_name or normalized_name(lesson['name']) == normalized_name(lesson_name))
                    and (not href or exercise.get('href') == href)
                ]
                if len(matches) > 1:
                    return None, None
                if not matches:
                    continue
                selected = matches[0]
                targets = self.page.locator(f'[data-cambridge-extractor-activity="{selected["dom_id"]}"]')
                for index in range(await targets.count()):
                    target = targets.nth(index)
                    if await target.is_visible():
                        await target.scroll_into_view_if_needed(timeout=3000)
                        return selected, target
            if self._last_scan_reached_end:
                snapshot = await self._evaluate_read(EXERCISES_DOM_SCRIPT, unit_name)
                matches = [exercise for lesson in snapshot['lessons'] for exercise in lesson['exercises']
                           if normalized_name(exercise['name']) == normalized_name(exercise_name)
                           and (not lesson_name or normalized_name(lesson['name']) == normalized_name(lesson_name))
                           and (not href or exercise.get('href') == href)]
                if len(matches) == 1:
                    selected = matches[0]
                    targets = self.page.locator(f'[data-cambridge-extractor-activity="{selected["dom_id"]}"]')
                    for index in range(await targets.count()):
                        target = targets.nth(index)
                        if not await target.evaluate("el => !!el.closest('[disabled], [aria-disabled=\"true\"], [inert]')"):
                            return selected, target
                break
        return None, None

    async def _wait_for_verified_exercise(self, expected, timeout=20000):
        for attempt in range(3):
            try:
                handle = await self.page.wait_for_function(VERIFY_ACTIVITY_SCRIPT, arg=expected, timeout=timeout)
                try:
                    return await handle.json_value()
                finally:
                    await handle.dispose()
            except PlaywrightError as error:
                if not self._is_navigation_error(error) or attempt == 2:
                    raise
                await asyncio.sleep(0.2)

    async def verify_current_exercise(self):
        if not self.verified_exercise:
            return False
        expected = {
            'name': self.verified_exercise['verified_title'],
            'href': (self.verified_exercise.get('href')
                     if self._is_exercise_url(self.verified_exercise.get('href') or '')
                     else self.verified_exercise['url']),
        }
        state = await self._evaluate_read(VERIFY_ACTIVITY_SCRIPT, expected)
        if not state:
            actual = await self._evaluate_read(ACTIVITY_STATE_SCRIPT)
            print(f"  {Fore.RED}{t('exercises_mismatch', expected=expected['name'], actual=actual['title'] or '?')}{Style.RESET_ALL}", flush=True)
            return False
        return True

    async def click_exercise(self, exercise_name, unit_name=None, lesson_name=None, href=None):
        print(f"  {Fore.CYAN}{t('exercises_opening', name=exercise_name)}{Style.RESET_ALL}", flush=True)
        unit_name = unit_name or self.current_unit
        if not unit_name or not await self.return_to_workbook(unit_name):
            return False

        selected, target = await self._locate_exercise(unit_name, exercise_name, lesson_name, href)
        if selected is None:
            print(f"  {Fore.RED}{t('exercises_ambiguous', name=exercise_name)}{Style.RESET_ALL}")
            return False

        expected_href = selected.get('href')
        if expected_href and not self._is_exercise_url(expected_href):
            expected_href = None
        expected = {'name': exercise_name, 'href': expected_href}
        self.reset_data_js_tracking()
        self._tracking_data_js = True
        try:
            async with report_progress('stage_open_exercise'):
                if await target.is_visible():
                    await target.click(timeout=10000)
                else:
                    # A real, exact catalog row can be CSS-hidden (e.g. a
                    # responsive/previous lesson). Activate that row, not a
                    # substring-matched parent. Never activate a disabled row.
                    activated = await target.evaluate(r'''(el, expected) => {
                        const norm = value => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
                        if (norm(el.textContent) !== norm(expected) || el.closest('[disabled], [aria-disabled="true"], [inert]')) return false;
                        el.click();
                        return true;
                    }''', exercise_name)
                    if not activated:
                        return False
                print(f"  {Fore.CYAN}{t('exercises_verifying', name=exercise_name)}{Style.RESET_ALL}", flush=True)
                state = await self._wait_for_verified_exercise(expected)
            self.verified_exercise = {
                'verification_version': 1,
                'verified_title': state['title'],
                'url': state['url'],
                'href': selected.get('href'),
                'unit': unit_name,
                'lesson': lesson_name,
            }
            print(f"  {Fore.GREEN}{t('exercises_opened')}{Style.RESET_ALL}", flush=True)
            return True
        except PlaywrightError as error:
            self._tracking_data_js = False
            actual_title = '?'
            with suppress(PlaywrightError):
                actual_title = (await self._evaluate_read(ACTIVITY_STATE_SCRIPT))['title'] or '?'
            print(f"  {Fore.RED}{t('exercises_mismatch', expected=exercise_name, actual=actual_title)}{Style.RESET_ALL}", flush=True)
            if not isinstance(error, PlaywrightTimeoutError):
                print(f"  {Fore.RED}{error}{Style.RESET_ALL}")
            return False

    def _parse_js_object(self, content):
        m = re.search(r'ajaxData\s*=\s*', content)
        if not m:
            return None

        start_idx = m.end()
        decoder = json.JSONDecoder()
        try:
            data, end_idx = decoder.raw_decode(content, start_idx)
            return data
        except json.JSONDecodeError:
            last_brace = content.rfind('}')
            if last_brace > start_idx:
                snippet = content[start_idx:last_brace + 1]
                try:
                    data = json.loads(snippet)
                    return data
                except Exception:
                    return None
            return None
        except Exception:
            return None

    async def get_answers_from_data_js(self):
        if not self.data_js_urls or not await self.verify_current_exercise():
            return None

        generation = self._data_js_generation
        urls = list(dict.fromkeys(reversed(self.data_js_urls)))
        for index, url in enumerate(urls, 1):
            content = self.data_js_contents.get(url)
            if not content:
                print(f"  {Fore.CYAN}{t('datajs_downloading', n=index, total=len(urls))}{Style.RESET_ALL}", flush=True)
                try:
                    # Use the authenticated browser context, not a blocking requests.get.
                    async with report_progress('stage_download'):
                        response = await self.context.request.get(url, timeout=30000)
                        try:
                            if not response.ok:
                                print(f"  {Fore.YELLOW}{t('datajs_http_failed', status=response.status)}{Style.RESET_ALL}")
                                continue
                            content = await response.text()
                        finally:
                            await response.dispose()
                except PlaywrightError as error:
                    print(f"  {Fore.YELLOW}{t('datajs_read_failed', error=type(error).__name__)}{Style.RESET_ALL}")
                    continue
            if generation != self._data_js_generation or not content:
                return None

            print(f"  {Fore.CYAN}{t('datajs_decoding', n=index, total=len(urls))}{Style.RESET_ALL}", flush=True)
            async with report_progress('stage_decode'):
                data = await asyncio.to_thread(self._parse_js_object, content)
            if not isinstance(data, dict):
                continue
            xml_count = sum(isinstance(name, str) and name.endswith('.xml') and isinstance(value, str)
                            for name, value in data.items())
            if not xml_count:
                continue
            if generation != self._data_js_generation or not await self.verify_current_exercise():
                return None
            self._tracking_data_js = False
            print(f"  {Fore.GREEN}{t('datajs_decoded', n=xml_count)}{Style.RESET_ALL}", flush=True)
            return data
        return None

    async def close(self):
        self._tracking_data_js = False
        tasks = list(self._data_js_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._data_js_requests.clear()
        if self.context:
            with suppress(PlaywrightError):
                await self.context.close()
        if self.playwright:
            with suppress(PlaywrightError):
                await self.playwright.stop()
        self.context = self.browser = self.page = self.playwright = None


def display_courses(courses):
    print(f"\n  {'=' * 70}")
    print(f"  {Fore.CYAN}{t('courses_header')}{Style.RESET_ALL}")
    print(f"  {'=' * 70}\n")
    if not courses:
        print(f"  {Fore.YELLOW}{t('courses_not_found')}{Style.RESET_ALL}")
        return
    for i, course in enumerate(courses, 1):
        print(f"  {Fore.WHITE}[{i}]{Style.RESET_ALL} {Fore.CYAN}{course['courseName']}{Style.RESET_ALL}")
        print(f"      {Fore.GREEN}{course['workbookName']}{Style.RESET_ALL}\n")

def display_units(units):
    print(f"\n  {'=' * 70}")
    print(f"  {Fore.CYAN}{t('units_header')}{Style.RESET_ALL}")
    print(f"  {'=' * 70}\n")
    if not units:
        print(f"  {Fore.YELLOW}{t('units_not_found')}{Style.RESET_ALL}")
        return
    for i, unit in enumerate(units, 1):
        print(f"  {Fore.WHITE}[{i}]{Style.RESET_ALL} {Fore.CYAN}{unit['name']}{Style.RESET_ALL}")

def display_exercises(data):
    print(f"\n  {'=' * 70}")
    print(f"  {Fore.CYAN}{data['unit_name']}{Style.RESET_ALL}")
    print(f"  {'=' * 70}\n")
    if data.get('discovery', {}).get('complete') is False:
        print(f"  {Fore.YELLOW}{t('exercises_catalog_incomplete')}{Style.RESET_ALL}")
    if not data.get('lessons'):
        print(f"  {Fore.YELLOW}{t('exercises_none')}{Style.RESET_ALL}")
        return
    exercise_counter = 1
    for lesson in data['lessons']:
        print(f"  {Fore.MAGENTA}+-- {lesson['name']}{Style.RESET_ALL}")
        for ex in lesson['exercises']:
            if ex['status'] == 'completed':
                print(f"  {Fore.GREEN}|   [{exercise_counter}] [OK] {ex['name']}{Style.RESET_ALL}")
            elif ex['status'] == 'in-progress':
                print(f"  {Fore.YELLOW}|   [{exercise_counter}] [..] {ex['name']}{Style.RESET_ALL}")
            else:
                print(f"  {Fore.WHITE}|   [{exercise_counter}] [  ] {ex['name']}{Style.RESET_ALL}")
            exercise_counter += 1
        print(f"  {Fore.MAGENTA}+--{Style.RESET_ALL}\n")

def choose_account(scraper):
    while True:
        accounts = scraper.load_accounts()
        clear_screen()
        print(f"\n  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{t('accounts_header')}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")

        if accounts:
            for i, account in enumerate(accounts, 1):
                has_pwd = f" {t('accounts_saved_pwd')}" if account.get('password') else ''
                print(f"  [{i}] {account.get('email', '')}{has_pwd}")
        else:
            print(f"  {Fore.YELLOW}{t('accounts_empty')}{Style.RESET_ALL}")

        print(f"\n  {Fore.CYAN}[A] {t('accounts_add')}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}[0] {t('accounts_cancel')}{Style.RESET_ALL}")

        try:
            choice = input(f"\n  {Fore.CYAN}[>] {t('accounts_select')}: {Style.RESET_ALL}").strip()
        except (EOFError, KeyboardInterrupt):
            return None, None, False

        if choice == '0' or not choice:
            return None, None, False

        if choice.lower() == 'a':
            try:
                new_email = input(f"\n  {Fore.CYAN}[>] {t('accounts_new_email')}: {Style.RESET_ALL}").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not new_email or '@' not in new_email:
                print(f"  {Fore.RED}{t('accounts_invalid_email')}{Style.RESET_ALL}")
                time.sleep(1)
                continue
            scraper.save_account(new_email, None)
            print(f"  {Fore.GREEN}{t('accounts_added', email=new_email)}{Style.RESET_ALL}")
            time.sleep(1)
            return new_email, None, True

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(accounts):
                acc = accounts[idx]
                return acc.get('email', ''), acc.get('password'), True
        except ValueError:
            pass

        if '@' in choice:
            return choice, None, True

        print(f"  {Fore.RED}{t('accounts_invalid_choice')}{Style.RESET_ALL}")
        time.sleep(1)

async def show_answers_flow(scraper, db):
    email, saved_password, should_continue = choose_account(scraper)
    if not should_continue or not email:
        print(f"\n  {Fore.YELLOW}{t('login_cancel')}{Style.RESET_ALL}")
        return

    try:
        profile_dir = scraper._profile_dir(email)
        print(f"  {Fore.CYAN}{t('login_opening_profile', path=profile_dir)}{Style.RESET_ALL}")
        await scraper.init_browser(profile_dir)
        print(f"  {Fore.GREEN}{t('login_browser_opened')}{Style.RESET_ALL}")

        login_success = await scraper.check_login_status()

        if login_success:
            print(f"  {Fore.GREEN}{t('login_session_ok')}{Style.RESET_ALL}")
        else:
            password = None
            if saved_password:
                print(f"  {Fore.GREEN}{t('login_use_saved_pwd')}{Style.RESET_ALL}")
                password = saved_password
            else:
                password = (await console_input(f"  {Fore.CYAN}{t('login_enter_pwd', email=email)}{Style.RESET_ALL}", reader=masked_input)).strip()
                if password:
                    try:
                        save_choice = (await console_input(f"  {Fore.CYAN}{t('login_save_pwd_q')}{Style.RESET_ALL}")).strip()
                    except Exception:
                        save_choice = '0'
                    if save_choice == '1':
                        scraper.save_account(email, password)
                        print(f"  {Fore.GREEN}{t('login_pwd_saved')}{Style.RESET_ALL}")

            if not password:
                print(f"  {Fore.RED}{t('login_no_pwd')}{Style.RESET_ALL}")
                await scraper.close()
                return

            login_success = await scraper.login(email, password)
            if login_success:
                scraper.save_account(email)  # Remember the account, not an unrequested password.

        if not login_success:
            print(f"  {Fore.RED}{t('login_failed')}{Style.RESET_ALL}")
            await scraper.close()
            return

        await scraper.debug_wait(1)
        clear_screen()

        while True:
            courses = await scraper.get_courses_with_workbooks()
            display_courses(courses)
            if not courses:
                print(f"  {Fore.YELLOW}{t('courses_not_found')}{Style.RESET_ALL}")
                try:
                    await console_input(f"\n  {Fore.CYAN}{t('input_enter_close')}{Style.RESET_ALL}")
                except Exception:
                    pass
                return

            print(f"  {Fore.CYAN}{t('courses_select')}{Style.RESET_ALL}")
            for i, course in enumerate(courses, 1):
                print(f"  {i}. {course['courseName']}")
            print(f"  0. {t('courses_refresh')}")
            print(f"  X. {t('courses_exit')}")

            try:
                choice = (await console_input(f"\n  {Fore.CYAN}[>] {t('courses_select')}{Style.RESET_ALL}")).strip()
            except (EOFError, KeyboardInterrupt):
                return

            if choice.lower() == 'x':
                print(f"\n  {Fore.CYAN}{t('exit_program')}{Style.RESET_ALL}")
                await scraper.close()
                sys.exit(0)

            if choice == '0' or not choice:
                clear_screen()
                continue

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(courses):
                    selected_course = courses[idx]
                    clear_screen()
                    if await scraper.click_workbook(selected_course['courseName']):
                        await run_unit_selection(scraper, db, selected_course)
                        clear_screen()
                else:
                    print(f"  {Fore.RED}{t('accounts_invalid_choice')}{Style.RESET_ALL}")
                    await scraper.debug_wait(1)
                    clear_screen()
            except ValueError:
                print(f"  {Fore.RED}{t('input_number')}{Style.RESET_ALL}")
                await scraper.debug_wait(1)
                clear_screen()

    except SystemExit:
        raise
    except Exception as e:
        print(f"\n  {Fore.RED}{t('error_prefix', msg=e)}{Style.RESET_ALL}")
        traceback.print_exc()
    finally:
        try:
            await scraper.close()
        except Exception:
            pass

async def run_unit_selection(scraper, db, selected_course):
    while True:
        units = await scraper.get_all_units()
        if not units:
            print(f"  {Fore.YELLOW}{t('units_not_found')}{Style.RESET_ALL}")
            try:
                await console_input(f"\n  {Fore.CYAN}{t('input_enter_back')}{Style.RESET_ALL}")
            except Exception:
                pass
            return

        clear_screen()
        display_units(units)
        print(f"\n  {Fore.CYAN}[0] {t('units_back')}{Style.RESET_ALL}")

        try:
            unit_choice = (await console_input(f"\n  {Fore.CYAN}{t('units_select')}{Style.RESET_ALL}")).strip()
        except (EOFError, KeyboardInterrupt):
            return

        if unit_choice == '0' or not unit_choice:
            return

        try:
            unit_idx = int(unit_choice) - 1
            if 0 <= unit_idx < len(units):
                selected_unit = units[unit_idx]
                clear_screen()
                if not await scraper.click_unit(selected_unit['name']):
                    continue
                await run_exercise_selection(scraper, db, selected_course, selected_unit)
            else:
                print(f"  {Fore.RED}{t('accounts_invalid_choice')}{Style.RESET_ALL}")
                await scraper.debug_wait(1)
        except ValueError:
            print(f"  {Fore.RED}{t('input_number')}{Style.RESET_ALL}")
            await scraper.debug_wait(1)

async def show_selected_exercise(scraper, db, selected_course, selected_unit, selected_ex):
    exercise_name = selected_ex['name']
    lesson_name = selected_ex['lesson']
    print(f"\n  {Fore.CYAN}{t('exercises_selected', name=exercise_name)}{Style.RESET_ALL}")
    cached = db.get(selected_course['courseName'], selected_unit['name'], exercise_name, lesson=lesson_name)
    use_cache = False
    if cached:
        if cache_matches_exercise(cached, selected_ex, selected_unit['name']):
            print(f"  {Fore.GREEN}{t('cached_found', time=cached.get('saved_at', ''))}{Style.RESET_ALL}")
            use_cache = (await console_input(f"  {Fore.CYAN}{t('cached_use_q')}{Style.RESET_ALL}")).strip() == '1'
        else:
            print(f"  {Fore.YELLOW}{t('cached_unverified')}{Style.RESET_ALL}")

    # Cached answers still open the exact selected activity in the browser.
    if not await scraper.click_exercise(
        exercise_name, unit_name=selected_unit['name'], lesson_name=lesson_name, href=selected_ex.get('href'),
    ):
        return
    if use_cache:
        scraper._tracking_data_js = False
        clear_screen()
        print(f"\n{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  {t('cached_header', name=exercise_name)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")
        for xml_name, questions in cached.get('answers', {}).items():
            gyatt_printquestions(xml_name, questions)
        return

    if not await scraper._wait_for_data_js(timeout=25):
        print(f"  {Fore.RED}{t('datajs_not_found')}{Style.RESET_ALL}")
        return
    data = await scraper.get_answers_from_data_js()
    if not data:
        print(f"  {Fore.RED}{t('datajs_parse_failed')}{Style.RESET_ALL}")
        return
    if not await scraper.verify_current_exercise():
        return

    clear_screen()
    print(f"\n{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  {t('answers_header', name=exercise_name)}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  {'=' * 60}{Style.RESET_ALL}")
    async with report_progress('stage_xml'):
        await asyncio.to_thread(
            skibidi_processxmlfiles, data, db=db,
            course=selected_course['courseName'], unit=selected_unit['name'],
            exercise=exercise_name, lesson=lesson_name, source=dict(scraper.verified_exercise),
        )


async def run_exercise_selection(scraper, db, selected_course, selected_unit):
    while True:
        # Also handles a browser that the user navigated manually while at a prompt.
        if not await scraper.return_to_workbook(selected_unit['name']):
            return
        exercises_data = await scraper.get_exercises_in_unit(selected_unit['name'])
        clear_screen()
        display_exercises(exercises_data)
        all_exercises = [
            dict(exercise, lesson=lesson['name'])
            for lesson in exercises_data.get('lessons', []) for exercise in lesson['exercises']
        ]
        print(f"\n  {Fore.CYAN}[0] {t('exercises_back')}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}[R] {t('exercises_refresh')}{Style.RESET_ALL}")
        try:
            ex_choice = (await console_input(f"\n  {Fore.CYAN}{t('exercises_select')}{Style.RESET_ALL}")).strip()
        except (EOFError, KeyboardInterrupt):
            await scraper.return_to_workbook()
            return
        if ex_choice.lower() == 'r':
            continue
        if ex_choice == '0' or not ex_choice:
            await scraper.return_to_workbook()
            return
        try:
            ex_idx = int(ex_choice) - 1
        except ValueError:
            print(f"  {Fore.RED}{t('input_number')}{Style.RESET_ALL}")
            continue
        if not 0 <= ex_idx < len(all_exercises):
            print(f"  {Fore.RED}{t('accounts_invalid_choice')}{Style.RESET_ALL}")
            continue

        stop = False
        try:
            await show_selected_exercise(scraper, db, selected_course, selected_unit, all_exercises[ex_idx])
        except (EOFError, KeyboardInterrupt):
            stop = True
        except Exception as error:
            # A failed activity should not discard the entire logged-in session.
            print(f"\n  {Fore.RED}{t('error_prefix', msg=error)}{Style.RESET_ALL}")
            traceback.print_exc()
        finally:
            if not stop:
                try:
                    await console_input(f"\n  {Fore.CYAN}{t('input_enter_exercises')}{Style.RESET_ALL}")
                except (EOFError, KeyboardInterrupt):
                    stop = True
            restored = await scraper.return_to_workbook(selected_unit['name'])
        if stop or not restored:
            return


def change_language_menu():
    while True:
        clear_screen()
        print(f"\n  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{t('lang_menu_header')}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}\n")
        print(f"  {Fore.WHITE}[1]{Style.RESET_ALL} {Fore.CYAN}{t('lang_th')}{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}[2]{Style.RESET_ALL} {Fore.CYAN}{t('lang_en')}{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}[0]{Style.RESET_ALL} {Fore.CYAN}{t('lang_back')}{Style.RESET_ALL}")
        print(f"\n  {Fore.GREEN}{t('lang_current')}{Style.RESET_ALL}")

        try:
            c = input(f"\n  {Fore.CYAN}[>] {Style.RESET_ALL}").strip()
        except (EOFError, KeyboardInterrupt):
            return

        if c == '1':
            Lang.current = 'th'
            Lang.save()
            print(f"  {Fore.GREEN}{t('lang_switched')}{Style.RESET_ALL}")
            time.sleep(1.2)
            return
        if c == '2':
            Lang.current = 'en'
            Lang.save()
            print(f"  {Fore.GREEN}{t('lang_switched')}{Style.RESET_ALL}")
            time.sleep(1.2)
            return
        if c == '0':
            return

async def main_async(db):
    scraper = CambridgeOneScraper()
    await show_answers_flow(scraper, db)

def skibidi_main():
    logger = SkibidiLogger(log_dir="logs")
    sys.stdout = logger
    sys.stderr = logger

    try:
        Lang.load()

        print(f"\n  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{t('log_session', path=logger.log_file)}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}\n")

        db = PomlikeheeyaDB("configs/answers_db.json")
        print(f"  {Fore.GREEN}{t('db_loaded', n=db.count())}{Style.RESET_ALL}")

        while True:
            clear_screen()
            print(UI_TEXT())

            try:
                choice = input(f"\n  {Fore.CYAN}{t('input_choice')}{Style.RESET_ALL}").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if choice == '4':
                print(f"\n  {Fore.CYAN}{t('goodbye')}{Style.RESET_ALL}")
                break

            elif choice == '3':
                change_language_menu()

            elif choice == '2':
                pom_showdatabase(db)

            elif choice == '1':
                try:
                    asyncio.run(main_async(db))
                except SystemExit:
                    print(f"\n  {Fore.CYAN}{t('goodbye')}{Style.RESET_ALL}")
                    break
                except Exception as e:
                    print(f"\n  {Fore.RED}{t('error_prefix', msg=e)}{Style.RESET_ALL}")
                    traceback.print_exc()

            else:
                print(f"{Fore.RED}  {t('input_invalid')}{Style.RESET_ALL}")
                time.sleep(1)

    except Exception as e:
        print(f"\n{Fore.RED}  {t('fatal_prefix', msg=e)}{Style.RESET_ALL}")
        traceback.print_exc()

    finally:
        print(f"\n  {Fore.CYAN}{t('log_saved', path=logger.log_file)}{Style.RESET_ALL}")
        logger.close()
        sys.stdout = logger.original_stdout
        sys.stderr = logger.original_stderr

if __name__ == "__main__":
    skibidi_main()