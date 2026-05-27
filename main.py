#!/usr/bin/env python3
"""
上海交通大学体育场馆自动预约脚本。

默认目标：
 - 学生中心
 - 学生中心健身房
 - 任一天
 - 15:00-16:00
 - 任一可用场地
"""

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from PIL import Image
import pytesseract
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_URL = "https://sports.sjtu.edu.cn/pc/#/"
TARGET_VENUE_IDS = {
    "学生中心": "d784ad7c-cb24-4282-afd6-a67aec68c675",
    "子衿街学生活动中心": "768214ba-3b1c-4f29-ad00-15c0e376b000",
}

TIME_SLOTS = [
    "07:00-08:00",
    "08:00-09:00",
    "09:00-10:00",
    "10:00-11:00",
    "11:00-12:00",
    "12:00-13:00",
    "13:00-14:00",
    "14:00-15:00",
    "15:00-16:00",
    "16:00-17:00",
    "17:00-18:00",
    "18:00-19:00",
    "19:00-20:00",
    "20:00-21:00",
    "21:00-22:00",
]


@dataclass
class SubmitResult:
    status: str
    message: str
    order_id: str = ""


def init_driver(
    chromedriver_path: Optional[str],
    headless: bool = False,
    user_data_dir: Optional[str] = None,
) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")

    if chromedriver_path:
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        # Selenium Manager will choose/download a ChromeDriver matching the local Chrome.
        driver = webdriver.Chrome(options=options)

    driver.set_window_size(1400, 900)
    return driver


def wait_and_click(driver: webdriver.Chrome, xpath: str, timeout: int = 15):
    el = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    el.click()
    return el


def clean_captcha_text(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", text or "")


def is_sports_logged_in(driver: webdriver.Chrome) -> bool:
    if "sports.sjtu.edu.cn" not in driver.current_url:
        return False
    try:
        return bool(driver.execute_script("return sessionStorage.getItem('token')"))
    except Exception:
        return False


def click_school_login(driver: webdriver.Chrome) -> None:
    if "sports.sjtu.edu.cn" not in driver.current_url:
        driver.get(BASE_URL)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    if is_sports_logged_in(driver):
        return
    wait_and_click(driver, "//button[normalize-space()='校内人员登录']", timeout=20)


def wait_for_sports_login(driver: webdriver.Chrome, timeout: int) -> bool:
    try:
        WebDriverWait(driver, timeout).until(lambda d: is_sports_logged_in(d))
        return True
    except TimeoutException:
        return False


def login(
    driver: webdriver.Chrome,
    user: str,
    pwd: str,
    save_dir: str = ".",
    max_attempts: int = 5,
    manual_login: bool = False,
    login_timeout: int = 90,
) -> bool:
    if is_sports_logged_in(driver):
        print("已检测到预约平台登录态")
        return True

    click_school_login(driver)
    WebDriverWait(driver, 30).until(
        lambda d: "jaccount.sjtu.edu.cn" in d.current_url or is_sports_logged_in(d)
    )
    if is_sports_logged_in(driver):
        print("已通过已有 JAccount 会话进入预约平台")
        return True

    if manual_login:
        print("请在浏览器中手动完成 JAccount 登录...")
        return wait_for_sports_login(driver, login_timeout)

    user_css = "#input-login-user"
    pass_css = "#input-login-pass"
    captcha_img_css = "#captcha-img"
    captcha_input_css = "#input-login-captcha"
    submit_css = "#submit-password-button"

    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, user_css)))

    for attempt in range(1, max_attempts + 1):
        try:
            driver.find_element(By.CSS_SELECTOR, user_css).clear()
            driver.find_element(By.CSS_SELECTOR, user_css).send_keys(user)
            driver.find_element(By.CSS_SELECTOR, pass_css).clear()
            driver.find_element(By.CSS_SELECTOR, pass_css).send_keys(pwd)
            time.sleep(0.5)

            captcha_path = os.path.join(save_dir, "captcha.png")
            captcha_el = driver.find_element(By.CSS_SELECTOR, captcha_img_css)
            captcha_el.screenshot(captcha_path)
            print(f"[尝试 {attempt}] captcha saved to: {captcha_path}")

            try:
                img = Image.open(captcha_path)
                text = clean_captcha_text(
                    pytesseract.image_to_string(img, config="--psm 7")
                )
                print(f"[尝试 {attempt}] OCR result: {text}")
            except Exception as exc:
                print(f"[尝试 {attempt}] OCR failed: {exc}")
                text = ""

            driver.find_element(By.CSS_SELECTOR, captcha_input_css).clear()
            driver.find_element(By.CSS_SELECTOR, captcha_input_css).send_keys(text)
            driver.find_element(By.CSS_SELECTOR, submit_css).click()

            if wait_for_sports_login(driver, 10):
                print(f"[尝试 {attempt}] 登录成功")
                return True

            print(f"[尝试 {attempt}] 登录未成功，刷新验证码后重试")
            try:
                driver.find_element(By.CSS_SELECTOR, captcha_img_css).click()
            except Exception:
                pass
            time.sleep(1)
        except Exception as exc:
            print(f"[尝试 {attempt}] 登录流程发生异常: {exc}")
            time.sleep(1)

    print(f"已达到最大尝试次数 ({max_attempts})，仍未登录成功")
    return False


def booking_url(venue_id: str, item_name: str) -> str:
    return f"{BASE_URL}apointmentDetails/1/{venue_id}/{quote(item_name)}/0"


def install_details_vm(driver: webdriver.Chrome) -> bool:
    return bool(
        driver.execute_script(
            """
            function findVue(vm, name) {
              if (!vm) return null;
              if (vm.$options && vm.$options.name === name) return vm;
              const children = vm.$children || [];
              for (let i = 0; i < children.length; i++) {
                const found = findVue(children[i], name);
                if (found) return found;
              }
              return null;
            }
            const app = document.querySelector('#app');
            const root = app && app.__vue__;
            const directEl = document.querySelector('#apointmentDetails');
            const direct = directEl && directEl.__vue__;
            window.__sjtu_vm = findVue(root, 'apointmentDetails') || direct || null;
            return !!window.__sjtu_vm;
            """
        )
    )


def get_vm_snapshot(driver: webdriver.Chrome) -> Dict[str, Any]:
    return driver.execute_script(
        """
        if (!window.__sjtu_vm) return {};
        const vm = window.__sjtu_vm;
        return {
          venueName: (vm.detailedData && vm.detailedData.venueName) || '',
          activeType: vm.isactiveName || '',
          activeTypeId: vm.isactiveId || '',
          weekCount: (vm.weekList || []).length,
          fieldCount: (vm.topSite || []).length,
          seatColumnCount: (vm.seatArray || []).length,
          loading: !!vm.loading,
          date: vm.timeData && vm.timeData.isdate,
          dateId: vm.dateId || '',
          messageText: document.body.innerText || ''
        };
        """
    )


def wait_for_details_ready(driver: webdriver.Chrome, timeout: int = 40) -> Dict[str, Any]:
    def ready(d):
        if not install_details_vm(d):
            return False
        snapshot = get_vm_snapshot(d)
        if snapshot.get("venueName") and snapshot.get("weekCount", 0) > 0:
            return snapshot
        return False

    return WebDriverWait(driver, timeout).until(ready)


def select_motion_type(driver: webdriver.Chrome, item_name: str) -> None:
    selected = driver.execute_script(
        """
        const vm = window.__sjtu_vm;
        const itemName = arguments[0];
        if (!vm) return {ok: false, reason: 'Vue instance not found'};
        if (vm.isactiveName === itemName) return {ok: true, changed: false};
        const match = (vm.tabList || []).find(x => x.name === itemName);
        if (!match) {
          return {ok: false, reason: '未找到项目: ' + itemName};
        }
        vm.handleClick({label: match.name, name: match.id});
        return {ok: true, changed: true};
        """,
        item_name,
    )
    if not selected.get("ok"):
        raise RuntimeError(selected.get("reason", "选择项目失败"))
    if selected.get("changed"):
        time.sleep(1)
        WebDriverWait(driver, 20).until(
            lambda d: install_details_vm(d)
            and get_vm_snapshot(d).get("activeType") == item_name
            and not get_vm_snapshot(d).get("loading")
        )


def wait_for_field_loaded(driver: webdriver.Chrome, target_date: str, timeout: int = 20) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: install_details_vm(d)
        and get_vm_snapshot(d).get("date") == target_date
        and not get_vm_snapshot(d).get("loading")
    )


def select_date(driver: webdriver.Chrome, index: int) -> Dict[str, Any]:
    result = driver.execute_script(
        """
        const vm = window.__sjtu_vm;
        const idx = arguments[0];
        const item = (vm.weekList || [])[idx];
        if (!item) return null;
        return {
          index: idx,
          date: item.isdate,
          view: item.viewStr,
          week: item.week,
          dateId: item.dateId || ''
        };
        """,
        index,
    )
    if not result:
        raise RuntimeError(f"日期索引无效: {index}")

    date_xpath = (
        "/html/body/div/div[2]/div[2]/div[2]/div[1]/div[2]/div[1]"
        f"/div/div/div/div[{index + 2}]/span/p"
    )
    try:
        date_el = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, date_xpath))
        )
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            date_el,
        )
        time.sleep(0.2)
        try:
            date_el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", date_el)
    except Exception as exc:
        print(f"日期 DOM 点击失败，尝试 Vue 方法切换: {exc}")
        switched = driver.execute_script(
            """
            const vm = window.__sjtu_vm;
            const item = (vm.weekList || [])[arguments[0]];
            if (!vm || !item || !vm.weekClick) return false;
            vm.weekClick(item);
            return true;
            """,
            index,
        )
        if not switched:
            raise

    time.sleep(0.8)
    wait_for_field_loaded(driver, result["date"])
    return result


def available_seats(driver: webdriver.Chrome, row_index: int) -> List[Dict[str, Any]]:
    return driver.execute_script(
        """
        const vm = window.__sjtu_vm;
        const rowIndex = arguments[0];
        const seats = [];
        const seatArray = vm.seatArray || [];
        const topSite = vm.topSite || [];
        for (let col = 0; col < seatArray.length; col++) {
          const row = seatArray[col] || [];
          const seat = row[rowIndex];
          if (seat && Number(seat.status) === 0) {
            seats.push({
              col,
              row: rowIndex,
              date: vm.timeData && vm.timeData.isdate,
              week: vm.timeData && vm.timeData.week,
              fieldName: topSite[col] && topSite[col].name,
              fieldId: topSite[col] && topSite[col].fieldId,
              price: seat.price,
              count: seat.count
            });
          }
        }
        return seats;
        """,
        row_index,
    )


def reset_selection(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        """
        const vm = window.__sjtu_vm;
        if (!vm) return;
        const seatArray = vm.seatArray || [];
        for (let col = 0; col < seatArray.length; col++) {
          for (let row = 0; row < (seatArray[col] || []).length; row++) {
            if (Number(seatArray[col][row].status) === 1) {
              seatArray[col][row].status = 0;
            }
          }
        }
        vm.buyLists = [];
        vm.allSun = 0;
        """
    )


def choose_seat(driver: webdriver.Chrome, seat: Dict[str, Any]) -> List[Dict[str, Any]]:
    reset_selection(driver)
    buy_lists = driver.execute_script(
        """
        const vm = window.__sjtu_vm;
        vm.handleChooseSeat(arguments[0], arguments[1]);
        return vm.buyLists || [];
        """,
        seat["col"],
        seat["row"],
    )
    if not buy_lists:
        raise RuntimeError("选择场地后 buyLists 为空")
    return buy_lists


def submit_order(driver: webdriver.Chrome, timeout: int = 30) -> SubmitResult:
    driver.execute_script(
        """
        const vm = window.__sjtu_vm;
        sessionStorage.removeItem('newOrderDetailsId');
        vm.ischecked = true;
        vm.disabled = false;
        vm.agreeTerms();
        """
    )

    deadline = time.time() + timeout
    last_message = ""
    while time.time() < deadline:
        state = driver.execute_script(
            """
            const messages = Array.from(
              document.querySelectorAll('.el-message__content')
            ).map(x => x.innerText).filter(Boolean);
            const box = document.querySelector('.verifybox');
            const captchaVisible = !!box &&
              box.getClientRects().length > 0 &&
              getComputedStyle(box).display !== 'none' &&
              getComputedStyle(box).visibility !== 'hidden';
            return {
              href: window.location.href,
              orderId: sessionStorage.getItem('newOrderDetailsId') || '',
              captcha: captchaVisible,
              messages
            };
            """
        )
        if state.get("orderId") or "/orderDetails/" in state.get("href", ""):
            return SubmitResult("success", "订单提交成功", state.get("orderId", ""))
        if state.get("captcha"):
            return SubmitResult("captcha", "服务器要求滑块验证，请改用非 headless 手动完成")
        if state.get("messages"):
            last_message = "；".join(state["messages"])
        time.sleep(0.5)
    return SubmitResult("failed", last_message or "提交订单超时")


def book(
    driver: webdriver.Chrome,
    venue: str,
    item_name: str,
    period: int,
) -> bool:
    venue_id = TARGET_VENUE_IDS.get(venue)
    if not venue_id:
        raise RuntimeError(f"未知场馆 {venue!r}，请在 TARGET_VENUE_IDS 中补充 venueId")

    row_index = period - 1
    if row_index < 0 or row_index >= len(TIME_SLOTS):
        raise RuntimeError(f"period 必须在 1-{len(TIME_SLOTS)} 之间")

    target_slot = TIME_SLOTS[row_index]
    url = booking_url(venue_id, item_name)
    print(f"打开预约详情页: {url}")
    driver.get(url)

    snapshot = wait_for_details_ready(driver)
    print(
        f"已进入 {snapshot.get('venueName')}，当前项目 {snapshot.get('activeType') or '未加载'}"
    )
    select_motion_type(driver, item_name)

    week_count = int(get_vm_snapshot(driver).get("weekCount", 0))
    success_count = 0
    for date_index in range(week_count - 1, -1, -1):
        try:
            date_info = select_date(driver, date_index)
            seats = available_seats(driver, row_index)
        except Exception as exc:
            print(f"日期索引 {date_index} 加载失败，切换到前一天: {exc}")
            continue

        if not seats:
            print(f"{date_info['view']} {target_slot} 无可用场地")
            continue

        seat = seats[0]
        print(
            f"{date_info['view']} {target_slot} 找到 {len(seats)} 个可用场地，"
            f"尝试 {seat.get('fieldName')}"
        )

        try:
            buy_lists = choose_seat(driver, seat)
            print(
                "已选择: "
                + ", ".join(
                    f"{x.get('subSitename')} {x.get('scheduleTime')}"
                    for x in buy_lists
                )
            )
            result = submit_order(driver)
            print(f"提交结果: {result.status} {result.message}")
            if result.status == "success":
                success_count += 1
                print(f"{date_info['view']} 预约成功，继续遍历前一天")
                driver.get(url)
                wait_for_details_ready(driver)
                select_motion_type(driver, item_name)
                continue
            if result.status == "captcha":
                print("遇到滑块验证，结束本轮遍历")
                return success_count > 0
            print(f"{date_info['view']} 提交未成功，切换到前一天")
        except Exception as exc:
            print(f"{date_info['view']} 场地 {seat.get('fieldName')} 尝试失败，切换到前一天: {exc}")
        finally:
            reset_selection(driver)

    if success_count:
        print(f"本轮遍历完成，成功预约 {success_count} 天")
        return True

    print(f"本轮遍历完成，没有成功预约任一天 {target_slot}")
    return False


def run_attempt(args: argparse.Namespace) -> bool:
    driver = None
    try:
        driver = init_driver(
            args.chromedriver,
            headless=args.headless,
            user_data_dir=args.user_data_dir,
        )
        driver.get(BASE_URL)
        if not login(
            driver,
            args.user,
            args.password,
            save_dir=args.captcha_dir,
            max_attempts=args.max_login_attempts,
            manual_login=args.manual_login,
            login_timeout=args.login_timeout,
        ):
            return False
        return book(
            driver,
            venue=args.venue,
            item_name=args.item_name,
            period=args.period,
        )
    except Exception as exc:
        print(f"预约尝试发生异常: {exc}")
        return False
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def parse_clock(value: str) -> dt_time:
    try:
        hour, minute = value.split(":", 1)
        return dt_time(int(hour), int(minute))
    except Exception as exc:
        raise argparse.ArgumentTypeError("时间格式应为 HH:MM") from exc


def next_window_start(now: datetime, start: dt_time) -> datetime:
    today = datetime(now.year, now.month, now.day, start.hour, start.minute)
    if now < today:
        return today
    return today + timedelta(days=1)


def run_with_schedule(args: argparse.Namespace) -> int:
    window_start = args.start_time
    window_minutes = args.window_minutes

    while True:
        now = datetime.now()
        start_dt = datetime(now.year, now.month, now.day, window_start.hour, window_start.minute)
        end_dt = start_dt + timedelta(minutes=window_minutes)

        if not (start_dt <= now < end_dt):
            next_start = next_window_start(now, window_start)
            seconds_until_start = max(1, int((next_start - now).total_seconds()))
            sleep_seconds = max(1, seconds_until_start // 2)
            next_end = next_start + timedelta(minutes=window_minutes)
            print(
                f"[{now:%Y-%m-%d %H:%M:%S}] 当前不在 "
                f"{next_start.strftime('%H:%M')}-{next_end.strftime('%H:%M')} 窗口，"
                f"距下次开始还有 {seconds_until_start} 秒，"
                f"等待 {sleep_seconds} 秒后再次检查"
            )
            time.sleep(sleep_seconds)
            continue

        print(
            f"[{now:%Y-%m-%d %H:%M:%S}] 进入预约窗口，"
            f"每 {args.retry_interval} 秒尝试一次"
        )
        while datetime.now() < end_dt:
            print("-" * 50)
            success = run_attempt(args)
            remaining = (end_dt - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            sleep_seconds = min(args.retry_interval, remaining)
            status = "有成功预约" if success else "未成功预约"
            print(f"本轮遍历完成（{status}），{int(sleep_seconds)} 秒后继续遍历")
            time.sleep(sleep_seconds)

        print("已超出本日预约窗口，等待下一天")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chromedriver",
        default=None,
        help="chromedriver 可执行文件路径；默认使用 Selenium Manager 自动匹配",
    )
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="123456")
    parser.add_argument("--venue", default="学生中心")
    parser.add_argument("--item-name", default="学生中心健身房")
    parser.add_argument(
        "--period",
        type=int,
        default=9,
        help="预约时间段，7:00-8:00 算 1，15:00-16:00 算 9",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--manual-login", action="store_true", help="手动完成 JAccount 登录")
    parser.add_argument("--login-timeout", type=int, default=120)
    parser.add_argument("--max-login-attempts", type=int, default=5)
    parser.add_argument("--captcha-dir", default=".")
    parser.add_argument("--user-data-dir", default=None)
    parser.add_argument("--test", action="store_true", help="测试模式：立即运行一次，不等待 12:00")
    parser.add_argument("--start-time", type=parse_clock, default=dt_time(12, 0))
    parser.add_argument("--window-minutes", type=int, default=10)
    parser.add_argument("--retry-interval", type=int, default=15)
    args = parser.parse_args()

    if args.manual_login and args.headless:
        print("--manual-login 需要可见浏览器，请不要同时使用 --headless")
        return 2

    if args.chromedriver:
        chromedriver_path = os.path.abspath(args.chromedriver)
        if not Path(chromedriver_path).exists():
            print("找不到 chromedriver，可执行文件路径:", chromedriver_path)
            return 1
        args.chromedriver = chromedriver_path

    Path(args.captcha_dir).mkdir(parents=True, exist_ok=True)

    if args.test:
        return 0 if run_attempt(args) else 1
    return run_with_schedule(args)


if __name__ == "__main__":
    sys.exit(main())
