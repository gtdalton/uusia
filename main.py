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
from dotenv import load_dotenv

load_dotenv()

@dataclasses.dataclass
class Loan:
    title: str
    due_date: datetime.date
    renewals_remaining: int
    status: str = ""

    def due_days(self):
        return (self.due_date - datetime.date.today()).days

    def is_due_for_renewal(self):
        return self.due_days() == 0 and self.renewals_remaining > 0


    def __repr__(self):
        if self.due_days() > 0:
            return f"{self.title} due in {self.due_days()} days ({self.due_date.strftime('%d %b %Y')}), {self.renewals_remaining} renewals remaining."
        elif self.due_days() == 0:
            return f"{self.title} is due today, Renewal: {self.status}, {self.renewals_remaining} renewals remaining."
        else:
            return f"{self.title} is overdue by {abs(self.due_days())}, Renewal: {self.status}, {self.renewals_remaining} renewals remaining."


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
    # if os.environ.get("GITHUB_ACTIONS") == "true"
    if not(os.environ.get("PYDEVD_USE_FRAME_EVAL")):
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


            #Clear cookies
            try:
                accept_btn = wait.until(EC.element_to_be_clickable((By.ID, "offcanvasCookie_req")))
                accept_btn.click()
            except:
                pass  # no cookie popup appeared, carry on

            print("Logging in...")
            element = wait.until(EC.element_to_be_clickable((By.ID, "navbarLoginMenuLink1")))
            element.click()

            username = os.getenv("SPYDUS_USERNAME")
            pin = os.getenv("SPYDUS_PIN")

            field = wait.until(EC.element_to_be_clickable((By.ID, "user_name")))
            field.clear()  # clear any existing text first
            field.send_keys(username)

            field = wait.until(EC.element_to_be_clickable((By.ID, "user_password")))
            field.clear()  # clear any existing text first
            field.send_keys(pin)

            field.send_keys(Keys.RETURN)


            current_loans = wait.until(EC.element_to_be_clickable((
                By.XPATH, '//div[@id="tabMYACCOUNT-body"]//a'
            )))
            session.login_success = True
            print("Logged in successfully! Finding loans")
            current_loans.click()

            loans = wait.until(EC.visibility_of_element_located((By.XPATH, '//div[@id="mainContent"]//tbody'))).find_elements(By.TAG_NAME, "tr")
            if not loans:
                print("No loans found")
                return session
            for i, loan_row in enumerate(loans):
                title = loan_row.find_element(By.XPATH, './/td/h3[@class="card-title mb-0"]/span/a/span').text
                due_date = datetime.datetime.strptime(
                    loan_row.find_element(By.XPATH, './/td[@data-caption="Due"]/span').text, "%d %b %Y"
                    ).date()
                renewals_remaining = 4 - int(re.search(r"\d+", loan_row.find_element(By.XPATH, './/span[contains(text(), "Renewed")]').text).group())
                loan = Loan(title, due_date, renewals_remaining)
                session.loans[title] = loan

                if loan.is_due_for_renewal():
                    #select due
                    loan_row.find_element(By.XPATH, f'.//input[@id="selCheck{i+1}"]').click()
            #Renew selections
            wait.until(EC.element_to_be_clickable((By.XPATH, '//a[text()="Renew selections"]'))).click()
            loans = wait.until(EC.visibility_of_element_located((By.XPATH, '//div[@class="result-content-records"]//tbody'))).find_elements(By.TAG_NAME, "tr")
            for loan_row in loans:
                title = loan_row.find_element(By.XPATH, './/td/h3[@class="card-title mb-0"]/span/a/span').text
                due_date = datetime.datetime.strptime(
                    loan_row.find_element(By.XPATH, './/td[@data-caption="Due"]/span').text, "%d %b %Y"
                ).date()
                status = loan_row.find_elements(By.TAG_NAME, "td")[4].find_element(By.XPATH, './/div').text
                session.loans[title].status = status
                if status == "Success":
                    session.loans[title].renewals_remaining -= 1
                session.loans[title].due_date = due_date
        except:
            driver.save_screenshot("debug.png")
        finally:
            return session






def send_email(session):
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    print("Sending email...")
    msg = MIMEText(str(session))
    msg["Subject"] = "Daily Library Loan Report"
    msg["From"] = f"Uusia Daily Email<{user}>"
    msg["To"] = user

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.send_message(msg)


def main():
    message = check_books()
    print(message)
    send_email(message)

if __name__ == "__main__":
    main()
