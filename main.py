import dataclasses
import os
import re
import smtplib
from email.mime.text import MIMEText
import datetime

from selenium import webdriver
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
    due_date: datetime.date
    renewals_remaining: int
    renewed: bool = False

    def due_days(self) -> int:
        return (self.due_date - datetime.date.today()).days

    def is_due_for_renewal(self) -> bool:
        return self.due_days() == 0 and self.renewals_remaining > 0

    def renew(self, due_date: datetime.date) -> None:
        self.due_date = due_date
        self.renewed = True
        self.renewals_remaining -= 1

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
class Session:
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
    session = Session()
    # Only open Selenium Chrome window during Pycharm Debug mode
    if not (os.environ.get("PYDEVD_LOAD_VALUES_ASYNC")):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    else:
        options = None
    with webdriver.Chrome(options=options) as driver:
        try:
            print("Loading page...")
            driver.get("https://brighton-hove.spydus.co.uk/")
            wait = WebDriverWait(driver, 10)  # wait up to 10 seconds

            # Clear cookies
            try:
                accept_btn = wait.until(EC.element_to_be_clickable((By.ID, "offcanvasCookie_req")))
                accept_btn.click()
            except:
                pass  # no cookie popup appeared, carry on

            print("Logging in...")
            element = wait.until(EC.element_to_be_clickable((By.ID, "navbarLoginMenuLink1")))
            element.click()

            username = os.getenv("SPYDUS_USERNAME")
            SPYDUS_PASSWORD = os.getenv("SPYDUS_PASSWORD")

            field = wait.until(EC.element_to_be_clickable((By.ID, "user_name")))
            field.clear()  # clear any existing text first
            field.send_keys(username)

            field = wait.until(EC.element_to_be_clickable((By.ID, "user_password")))
            field.clear()  # clear any existing text first
            field.send_keys(SPYDUS_PASSWORD)

            field.send_keys(Keys.RETURN)

            current_loans_button = wait.until(EC.element_to_be_clickable((
                By.XPATH, '//a[contains(@href, "LOANRENQ")]'
            )))
            session.login_success = True
            print("Logged in successfully! Finding loans")
            current_loans_button.click()

            loans = wait.until(
                EC.visibility_of_element_located((By.XPATH, '//div[@id="mainContent"]//tbody'))).find_elements(
                By.TAG_NAME, "tr")
            if not loans:
                print("No loans found")
                return session
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
                session.loans[title] = loan

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
                        session.loans[title].renew(due_date)


        except Exception as e:
            print(f"Exception: {e}: check debug screenshot")
            driver.save_screenshot("debug.png")
            with open("error.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)

        finally:
            return session


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
    message = check_books()
    print(message)
    send_email(message)


if __name__ == "__main__":
    main()
