import dataclasses
import os
import re
import smtplib
from email.mime.text import MIMEText
import datetime

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
import base64
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

# import undetected_chromedriver as uc
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
from dotenv import load_dotenv

load_dotenv()


@dataclasses.dataclass
class Loan:
    title: str
    renewal_link: str
    due_date: datetime.date
    renewals_remaining: int
    renewal_available: bool
    reserved_by_others: bool
    renewed: bool = False

    def due_days(self) -> int:
        return (self.due_date - datetime.date.today()).days

    def can_be_renewed(self) -> bool:
        return self.renewals_remaining > 0 and not self.reserved_by_others

    def is_due_for_renewal(self) -> bool:
        return self.due_days() == 0

    def should_be_renewed(self) -> bool:
        return self.is_due_for_renewal() and self.can_be_renewed()

    def must_be_returned(self):
        return self.renewals_remaining == 0 or self.reserved_by_others

    def get_status(self) -> tuple[int, str]:
        if self.renewed:
            return (1, "Renewed Today")
        elif self.due_days() < 0:
            return (3, "Overdue")
        elif self.renewals_remaining == 0:
            return (2, "Due for renewal")
        else:
            return (1, "On Loan")

    def table_row(self) -> list[str]:
        return [self.title, self.due_date.strftime("%d %b %Y"), self.renewals_remaining, self.get_status()]

    def __repr__(self) -> str:
        if self.due_days() > 0:
            return f"{self.title} due in {self.due_days()} days ({self.due_date.strftime('%d %b %Y')}), {self.renewals_remaining} renewals remaining."
        elif self.due_days() == 0:
            return f"{self.title} is due today, Renewal: {'Success!' if self.renewed else 'Failed'}, {self.renewals_remaining} renewals remaining."
        else:
            return f"{self.title} is overdue by {abs(self.due_days())}, Renewal: {'Success!' if self.renewed else 'Failed'}, {self.renewals_remaining} renewals remaining."


@dataclasses.dataclass
class SessionStatus:
    login_success: bool = False
    loans: dict[str, Loan] = dataclasses.field(default_factory=dict)

    def __repr__(self):
        if not self.login_success:
            return "Login failed"
        elif self.loans:
            return "\n\n".join([str(loan) for loan in self.loans.values()])
        else:
            return "No loans found"



def check_books():
    status = SessionStatus()
    # Only open Selenium Chrome window during Pycharm Debug mode
    if not (os.environ.get("PYDEVD_LOAD_VALUES_ASYNC")):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    else:
        options = None
    with uc.Chrome(options=options) as driver:
        try:
            print("Loading page...")
            driver.get("https://brighton-hove.spydus.co.uk/")
            wait = WebDriverWait(driver, 10)  # wait up to 10 seconds

            # click Begin button if it is shown
            try:
                button = wait.until(EC.element_to_be_clickable((By.ID, "amzn-captcha-verify-button")))
                print("Captcha...")
                button.click()
            except:
                pass

            # Clear cookies
            try:
                accept_btn = wait.until(EC.element_to_be_clickable((By.ID, "offcanvasCookie_req")))
                print("Accepting cookies...")
                accept_btn.click()
            except:
                pass  # no cookie popup appeared, carry on

            print("Logging in...")
            element = wait.until(EC.element_to_be_clickable((By.ID, "navbarLoginMenuLink1")))
            element.click()
            print("debug point 1")


            username = os.getenv("SPYDUS_USERNAME")
            SPYDUS_PASSWORD = os.getenv("SPYDUS_PASSWORD")

            field = wait.until(EC.element_to_be_clickable((By.ID, "user_name")))
            field.clear()  # clear any existing text first
            field.send_keys(username)

            field = wait.until(EC.element_to_be_clickable((By.ID, "user_password")))
            field.clear()  # clear any existing text first
            field.send_keys(SPYDUS_PASSWORD)

            print("Sending username/password")
            field.send_keys(Keys.RETURN)


            current_loans_button = wait.until(EC.element_to_be_clickable((
                By.XPATH, '//a[contains(@href, "LOANRENQ")]'
            )))
            status.login_success = True
            print("Logged in successfully! Finding loans")
            current_loans_button.click()

            loans = wait.until(
                EC.visibility_of_element_located((By.XPATH, '//div[@id="mainContent"]//tbody'))).find_elements(
                By.TAG_NAME, "tr")
            if not loans:
                print("No loans found")
                return status
            renewal_required = False
            for i, loan_row in enumerate(loans):
                title = loan_row.find_element(By.XPATH, './/td/h3[@class="card-title mb-0"]/span/a/span').text
                due_date = datetime.datetime.strptime(
                    loan_row.find_element(By.XPATH, './/td[@data-caption="Due"]/span').text, "%d %b %Y"
                ).date()
                try:
                    renewals_remaining = 4 - int(re.search(r"\d+", loan_row.find_element(By.XPATH,
                                                                                     './/span[contains(text(), "Renewed")]').text).group())
                except NoSuchElementException:
                    renewals_remaining = 4
                loan = Loan(title, due_date, renewals_remaining)
                status.loans[title] = loan

                if loan.is_due_for_renewal():
                    # select due
                    loan_row.find_element(By.XPATH, f'.//input[@id="selCheck{i + 1}"]').click()
                    renewal_required = True
            if renewal_required:
                # Renew selections
                wait.until(EC.element_to_be_clickable((By.XPATH, '//a[text()="Renew selections"]'))).click()
                loans = wait.until(EC.visibility_of_element_located(
                    (By.XPATH, '//div[@class="result-content-records"]//tbody'))).find_elements(By.TAG_NAME, "tr")

                for loan_row in loans:
                    title = loan_row.find_element(By.XPATH, './/td/h3[@class="card-title mb-0"]/span/a/span').text
                    due_date = datetime.datetime.strptime(
                        loan_row.find_element(By.XPATH, './/td[@data-caption="Due"]/span').text, "%d %b %Y"
                    ).date()
                    status = loan_row.find_elements(By.TAG_NAME, "td")[4].find_element(By.XPATH, './/div').text
                    if status == "Success":
                        status.loans[title].renew(due_date)


        except Exception as e:
            print(f"Exception: {e}: check debug screenshot")
            driver.save_screenshot("debug.png")
            with open("error.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)

        finally:
            return status

class CheckBooksAPI:
    def __init__(self):
        self.status = SessionStatus()
        self.session = requests.Session()
        self.base_url = "https://brighton-hove.spydus.co.uk/"

    @staticmethod
    def encrypt_password(password: str) -> str:
        PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
            MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC82Gt72tYMWhZsxs79+VFHgFP2
            kxeFvCuD/eg3NJOXAG9MMMDGzdQCCcbHDUXSHpwRE4ghacQrbr//JfBv+X5ZOeWU
            fnw3GUdlC+1CiPLlGzK/5oAl/hoKwaVt8K6MKqZphFsm5ftJbnc8xGNrbVG+AXB0
            bIAHZuvUILyfQV0+RwIDAQAB
            -----END PUBLIC KEY-----"""
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
        encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
        return base64.b64encode(encrypted).decode()

    def renew(self, loan: Loan):
        response = self.session.get(urljoin(self.base_url, loan.renewal_link))
        if response.status_code != 200:
            print(f"Could not renew: {loan.title}")

        body = response.text.lower()
        failure_patterns = [
            "unable",
            "cannot",
            "not renewed",
            "failed",
            "not possible",
            "max renew",
        ]
        failed = any(pattern in body for pattern in failure_patterns)
        if failed:
            loan.renewd = False
        try:
            new_due_date = BeautifulSoup(response.text, "html.parser").find("td", attrs={"data-caption": "Due"}).find("span").get_text(strip=True)
            loan.due_date = datetime.datetime.strptime(new_due_date, "%d %b %Y")
            print("Updated due date after renewal")
        except Exception as e:
            print("Failed to update due date after renewal")
            pass
        loan.renewed = True
        loan.renewals_remaining -= 1

    def run(self):
        # load login page
        login_page_url = self.base_url + "cgi-bin/spydus.exe/MSGTRN/OPAC/LOGINB"
        response = self.session.get(login_page_url)
        if response.status_code != 200:
            print(f"Failed to load login page: {login_page_url} : Error {response.status_code}")
            print("Status:", response.status_code)
            print("URL:", response.url)
            print("Method:", response.request.method)
            print("Response:", response.text[:1000])
            return self.status

        # login
        payload = {
            "BRWLID": os.getenv("SPYDUS_USERNAME"),
            "BRWLPWD": self.encrypt_password(os.getenv("SPYDUS_PASSWORD")),
            "RDT": "/cgi-bin/spydus.exe/PGM/OPAC/CCOPT/LB/1?ISGLB=1",
        }
        response = self.session.post(self.base_url+"cgi-bin/spydus.exe/PGM/OPAC/CCOPT/LB/2", data=payload)
        response_text = getattr(response, "text", "")

        if isinstance(response_text, str):
            soup = BeautifulSoup(response_text, "html.parser")
            if "log in" in response_text.lower() and "my library" not in response_text.lower():
                alert = soup.find("div", class_="alert")
                if alert:
                    print(f"Login failed: {alert.get_text(strip=True)}")
                else:
                    print("Login failed (credentials rejected or unknown error).")
                return self.status

        print("Login successful!")
        self.status.login_success = True

        #load dashboard
        dashboard_url = soup.find(
            "meta", attrs={"http-equiv": lambda value: value and value.lower() == "refresh"}
        )["content"].split("url=")[1]
        response = self.session.get(dashboard_url)
        response.raise_for_status()
        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        #Load loans
        loans_url = [anchor["href"] for anchor in soup.find_all("a") if "LOANRENQ" in anchor.get("href")][0]
        loans_soup = BeautifulSoup(self.session.get(urljoin(self.base_url, loans_url)).text, "html.parser")

        table = loans_soup.find("table")
        if not table:
            print("No loans found")
            return self.status


        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            details_cell = cells[2] if len(cells) >= 6 else cells[1]
            due_cell = cells[-3]
            status_cell = cells[-2]
            options_cell = cells[-1]

            title_link = details_cell.find("a", href=True)
            title = (
                title_link.get_text(" ", strip=True)
                if title_link
                else details_cell.get_text(" ", strip=True)
            )

            details_text = details_cell.get_text(" ", strip=True)
            details = (
                details_text[len(title):].strip(" -|")
                if details_text.startswith(title)
                else details_text
            )
            status_text = status_cell.get_text(" ", strip=True)
            reserved = any([r in status_text.lower() for r in ["reserv","request","queue","wait"]]) and any([s.isnumeric() for s in status_text])
            previously_renewed = re.search(r"Renewed\s*(\d+)", status_text)
            if previously_renewed:
                renewal_count = int(previously_renewed.group(1))
            else: renewal_count=0
            renew_text = options_cell.get_text(" ", strip=True).lower()

            self.status.loans[title] = Loan(
                title=title,
                renewal_link = options_cell.find("a", href=True).get("href"),
                due_date= datetime.datetime.strptime(due_cell.get_text(" ", strip=True),"%d %b %Y").date(),
                reserved_by_others=reserved,
                renewal_available= "renew" in renew_text,
                renewals_remaining=4-renewal_count
            )

        for loan in self.status.loans.values():
            print(loan)
            if loan.is_due_for_renewal():
                self.renew(loan)

        return self.status


def get_status_badge(level: int, text: str) -> str:
    match level:
        case 1:
            bg, color = "#d1e7dd", "#0a6640"
        case 2:
            bg, color = "#fff3cd", "#856404"
        case 3:
            bg, color = "#f8d7da", "#842029"
        case _:
            bg, color = "#ffffff", "#000000"

    return f'<span style="background-color: {bg}; color: {color}; padding: 3px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">{text}</span>'


def build_table(headers, rows):
    header_html = "".join(
        f'<th style="padding: 10px 14px; text-align: left; background-color: #f8f8f8; border-bottom: 2px solid #dddddd; font-size: 12px; color: #555555; text-transform: uppercase; letter-spacing: 0.5px;">{h}</th>'
        for h in headers
    )
    status_column_index = headers.index("Status")
    rows_html = ""
    for i, row in enumerate(rows):
        bg = "#ffffff" if i % 2 == 0 else "#fafafa"
        cells = ""
        for j, cell in enumerate(row):
            content = get_status_badge(*cell) if j == status_column_index else cell
            nowrap = "white-space: nowrap;" if j == status_column_index else ""
            cells += f'<td style="padding: 12px 14px; border-bottom: 1px solid #eeeeee; font-size: 14px; color: #333333; {nowrap}">{content}</td>'
        rows_html += f'<tr style="background-color: {bg};">{cells}</tr>'

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
        <tr>{header_html}</tr>
        {rows_html}
    </table>
    """


def build_email(title, content_html):
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 0; background-color: #f4f4f4; font-family: Arial, sans-serif;">

        <!-- outer wrapper -->
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f4f4; padding: 30px 0;">
        <tr><td align="center">

            <!-- card -->
            <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">

                <!-- header -->
                <tr>
                    <td style="background-color: #005EB8; padding: 24px 32px;">
                        <h1 style="margin: 0; color: #ffffff; font-size: 20px;">{title}</h1>
                    </td>
                </tr>

                <!-- body -->
                <tr>
                    <td style="padding: 32px;">
                        {content_html}
                    </td>
                </tr>

                <!-- footer -->
                <tr>
                    <td style="background-color: #f4f4f4; padding: 16px 32px; border-top: 1px solid #eeeeee;">
                        <p style="margin: 0; color: #999999; font-size: 12px;">
                            Generated automatically for {os.getenv("SPYDUS_USERNAME")}· {datetime.datetime.now().strftime("%d %b %Y %H:%M")}
                        </p>
                    </td>
                </tr>

            </table>

        </td></tr>
        </table>

    </body>
    </html>
    """


def send_email(session):
    EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
    msg = MIMEText(build_email(f"Loans", build_table(["Title", "Due Date", "Renewals Remaining", "Status"],
                                                    [loan.table_row() for loan in session.loans.values()])), "html")
    msg["Subject"] = "Daily Library Loan Report"
    msg["From"] = f"Uusia Daily Email<{EMAIL_USERNAME}>"
    msg["To"] = EMAIL_USERNAME

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(msg)


def main():
    client = CheckBooksAPI()
    message = client.run()
    print(message)
    send_email(message)


if __name__ == "__main__":
    main()
