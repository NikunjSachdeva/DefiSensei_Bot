import os
import logging
import requests
import sqlite3
import hashlib
import smtplib
import random
import time
import textwrap
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# --- Global Constants ---
TOKEN = os.getenv("TOKEN")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
GEMINI_API_KEY = "AIzaSyB0ZjCATMMJaujXqQVs45AyqTsrE-fWhWs"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
NEWS_API_URL = "https://newsapi.org/v2/top-headlines"

BUDGET_HIGHLIGHTS = [
    "*Income Tax:* There are no changes in the income tax slabs or rates. The new regime tax slabs remain as follows: no tax up to ₹3 lakh, 5% for income between ₹3-6 lakh, 10% for ₹6-9 lakh, 15% for ₹9-12 lakh, and 20% for ₹12-15 lakh. Income above ₹15 lakh is taxed at 30%.",
    "*Fiscal Deficit:* The fiscal deficit target for FY25 is set at 5.1% of GDP. This is part of a continued effort to reduce the fiscal deficit to 4.5% by FY26.",
    "*Economic Growth:* The budget continues to focus on macroeconomic stability and growth, with increased investments in infrastructure, agriculture, and domestic tourism.",
    "*Capital Expenditure:* Capital expenditure is increased by 11.1% to ₹11.11 lakh crore, which is 3.4% of GDP. This includes significant allocations for infrastructure projects.",
    "*Railways:* 40,000 normal rail bogies will be converted to Vande Bharat to enhance passenger safety and comfort. Three major railway corridors have also been announced.",
    "*Women's Empowerment:* The 'Lakhpati Didi' scheme aims to empower women in rural areas, with the target increased from 2 crore to 3 crore women benefiting from the program.",
    "*Defense:* The budget includes a significant allocation for defense to ensure national security and modernization of the armed forces.",
    "*Customs Duty:* No changes have been made to the customs duties, maintaining the status quo to provide stability for businesses.",
    "*Digital Infrastructure:* Continued investment in digital infrastructure is emphasized, with a focus on Global Capability Centres (GCCs) and digital transformation.",
    "*Green Energy:* Support for green energy initiatives continues, with significant investments in renewable energy projects.",
    "*Healthcare:* The budget allocates funds for the improvement of healthcare infrastructure and services, aiming to make healthcare more accessible and affordable.",
    "*Education:* Increased funding for educational initiatives, including skill development and vocational training programs.",
    "*Stock Market:* The budget is expected to positively impact the stock market with its focus on fiscal discipline and growth-oriented measures.",
    "*Middle Class:* Despite no changes in tax rates, the budget includes measures to simplify tax laws and improve compliance, which could benefit the middle class by making tax filing easier.",
    "*Lower Class:* Programs aimed at poverty alleviation and social welfare continue to receive funding, ensuring support for the lower class.",
    "*Upper Middle Class:* Initiatives to boost housing, infrastructure, and digital services benefit the upper middle class by improving the overall quality of life and economic opportunities.",
    "*Agriculture:* Significant investment in the agriculture sector, including subsidies and support for farmers to boost productivity and income.",
    "*Tourism:* Increased funding for domestic tourism to promote cultural heritage and boost local economies.",
    "*Government Expenditure:* The budget maintains a focus on prudent government expenditure to ensure long-term economic stability.",
    "*Economic Corridors:* Development of commodity-specific economic rail corridors to reduce logistics costs and improve competitiveness in manufacturing."
]

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Setup ---
def init_database():
    with sqlite3.connect('users.db') as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_verified INTEGER DEFAULT 0,
                is_logged_in INTEGER DEFAULT 0
            )
        ''')
        conn.commit()

# --- Utility Functions ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def escape_markdown_v2(text):
    if text is None:
        return ""
    escape_chars = r'[_*\[\]()~`>#+-=|{}.!]'
    return re.sub(escape_chars, r'\\\g<0>', text)

def handle_error(update: Update, message: str, error: Exception = None):
    if error:
        logger.error(f"Error: {str(error)}")
    return update.message.reply_text(message)

# --- Email Utilities ---
def send_mail(email: str, subject: str, body: str) -> bool:
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, email, msg.as_string())
        logger.info("Email sent successfully!")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

def send_delete_mail(username: str, email: str) -> bool:
    return send_mail(email, "Account Deletion Confirmation",
                    f"Dear {username},\n\nYour account has been successfully deleted.\n\nBest regards,\nDeFiSensei Team")

def send_otp_email(email: str, otp: int) -> bool:
    return send_mail(email, "Your OTP Code", f"Your OTP code is {otp}. It is valid for 5 minutes.")

# --- OTP Utilities ---
otp_storage = {}

def generate_otp():
    return random.randint(100000, 999999)

def store_otp(email: str, otp: int):
    otp_storage[email] = {'otp': otp, 'expiry': time.time() + 300}  # 5 minutes expiry

def verify_otp(email: str, otp: int) -> bool:
    stored = otp_storage.get(email)
    if not stored or time.time() > stored['expiry'] or stored['otp'] != int(otp):
        return False
    return True

# --- Stock and Forex Data Fetching ---
def fetch_stock_price(symbol: str) -> tuple:
    try:
        stock = yf.Ticker(symbol)
        data = stock.history(period="1d")
        if data.empty:
            return None, f"No price data found for {symbol}"
        return data['Close'].iloc[0], None
    except Exception as e:
        logger.error(f"Error fetching stock price for {symbol}: {str(e)}")
        return None, f"Unexpected error fetching stock price: {str(e)}"

def get_top_stocks(symbols: list) -> list:
    stocks = []
    for symbol in symbols:
        price, error = fetch_stock_price(symbol)
        if price is not None:
            stocks.append({'name': symbol, 'current_price': price})
        else:
            logger.error(f"No price data for {symbol}")
    return stocks

def get_top_stocks_worldwide():
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
    return get_top_stocks(symbols)

def get_top_stocks_india():
    symbols = ["RELIANCE.BO", "TCS.BO", "INFY.BO", "HDFCBANK.BO", "HINDUNILVR.BO"]
    return get_top_stocks(symbols)

def fetch_forex_rate(from_currency: str, to_currency: str) -> tuple:
    try:
        base_url = "https://www.alphavantage.co/query"
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "apikey": ALPHA_VANTAGE_API_KEY
        }
        response = requests.get(base_url, params=params)
        if response.status_code == 200:
            data = response.json()
            if "Realtime Currency Exchange Rate" in data:
                return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"]), None
            return None, f"No data available for {from_currency}/{to_currency}"
        return None, f"Failed to fetch data for {from_currency}/{to_currency}"
    except Exception as e:
        logger.error(f"Error fetching forex rate for {from_currency}/{to_currency}: {str(e)}")
        return None, "An unexpected error occurred"

def get_forex_prices():
    forex_pairs = {"USD/INR": None, "EUR/INR": None, "GBP/INR": None}
    for pair in forex_pairs:
        from_currency, to_currency = pair.split('/')
        rate, _ = fetch_forex_rate(from_currency, to_currency)
        if rate:
            forex_pairs[pair] = rate
    return forex_pairs

def get_stock_details(symbol: str) -> dict:
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        return {
            'Name': info.get('longName', 'N/A'),
            'Symbol': info.get('symbol', 'N/A'),
            'Exchange': info.get('exchange', 'N/A'),
            'Current Price': info.get('currentPrice', 'N/A'),
            'Market Cap': info.get('marketCap', 'N/A'),
            'PE Ratio': info.get('trailingPE', 'N/A'),
            '52 Week High': info.get('fiftyTwoWeekHigh', 'N/A'),
            '52 Week Low': info.get('fiftyTwoWeekLow', 'N/A'),
            'Dividend Yield': info.get('dividendYield', 'N/A'),
            'Description': info.get('description', 'N/A')
        }
    except Exception as e:
        logger.error(f"Error fetching stock details for {symbol}: {str(e)}")
        return {}

# --- Prediction Utilities ---
def download_and_preprocess_data(ticker: str, start='2020-01-01', end='2023-01-01', retries=3, delay=5):
    for attempt in range(retries):
        try:
            stock_data = yf.download(ticker, start=start, end=end, progress=False)
            if stock_data.empty:
                logger.warning(f"[Attempt {attempt + 1}] Empty data for {ticker}. Retrying in {delay}s...")
                time.sleep(delay)
                continue
            stock_data.ffill(inplace=True)
            stock_data['Return'] = stock_data['Close'].pct_change()
            stock_data.dropna(inplace=True)
            features = stock_data[['Open', 'High', 'Low', 'Close', 'Volume']].values
            labels = stock_data['Return'].values
            if len(features) == 0 or len(labels) == 0:
                raise ValueError("No features or labels available after preprocessing")
            return features, labels
        except Exception as e:
            logger.error(f"[Attempt {attempt + 1}] Error: {str(e)}. Retrying in {delay}s...")
            time.sleep(delay)
    raise RuntimeError(f"Failed to download or preprocess data for {ticker} after {retries} attempts")

def train_model(features, labels):
    X_train, X_test, y_train, y_test = train_test_split(features, labels, test_size=0.2, random_state=42)
    model = LinearRegression()
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    mse = mean_squared_error(y_test, predictions)
    logger.info(f'Mean Squared Error: {mse}')
    return model

def get_latest_stock_prices(ticker: str):
    try:
        stock_data = yf.download(ticker, period='1d', progress=False)
        if stock_data.empty:
            return None
        return stock_data.iloc[-1][['Open', 'High', 'Low', 'Close', 'Volume']].values
    except Exception as e:
        logger.error(f"Failed to fetch data for {ticker}: {str(e)}")
        return None

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("""
Hii!! Welcome to DeFiSensei.
Thank you for choosing this bot.
Let's get you registered to experience account-related features.
Type /register to start registration process.
Type /help to view available commands.
PS: Most features are now accessible without login!
                                    """)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        """
Available commands with their usage:

Enter the commands without <>

To interact with AI Finance assistant ChatBot, simply type the prompt without any slash or command.

Most commands no longer require login, except for account management features.

/start - Welcome message
/help - List available commands
/coin <coin name> - Know the current price of a coin. Eg: /coin bitcoin
/market - Get live market updates including top stocks worldwide, top stocks in India, and forex prices
/register <username> <password> <email> - Register a new account
/login <username> <password> - Login to your account
/logout - Logout from your account
/delete <username> <password> <email> - Delete your account
/forex <from> <to> - Get live price for a specific forex
/stock <stock symbol (i.e., stockname.BO for Indian stock or stocksymbol for global)> - Get live price for a specific stock
/budget_highlights - Highlights for 2024 India Budget
/finance_news - Get the latest finance news
/recover_username <email> - Recover your username using your email
/reset_password <email> <new_password> - Reset your account password
/predict <stock symbol (i.e., stockname.BO for Indian stock or stocksymbol for global)> - Predict investment return using AI
/search <stockname> - Search for stocks and financial information. Eg: /search infosys
        """
    )

async def coin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /coin <coin name>")
        return
    coin = context.args[0].lower()
    try:
        response = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=inr")
        if response.status_code == 200:
            data = response.json()
            if coin in data:
                await update.message.reply_text(f"The current price of {coin} is ₹{data[coin]['inr']}")
            else:
                await update.message.reply_text(f"Coin '{coin}' not found.")
        else:
            await handle_error(update, "Failed to fetch price data.")
    except Exception as e:
        await handle_error(update, "An unexpected error occurred.", e)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 3:
        await update.message.reply_text("Usage: /register <username> <password> <email>")
        return
    username, password, email = context.args
    password_hash = hash_password(password)
    telegram_id = update.message.from_user.id

    try:
        with sqlite3.connect('users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (telegram_id, username, email, password_hash) VALUES (?, ?, ?, ?)',
                          (telegram_id, username, email, password_hash))
            conn.commit()
        if send_mail(email, "Registration Confirmation", "You have successfully registered for DeFiSensei. Thank you!"):
            await update.message.reply_text("Registration successful!! Please check your email for confirmation.")
        else:
            await update.message.reply_text("Failed to send confirmation email. Please check the email address and try again.")
    except sqlite3.IntegrityError:
        await update.message.reply_text("This user already exists. Please try logging in.")
    except Exception as e:
        await handle_error(update, "An error occurred during registration.", e)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text('Usage: /login <username> <password>')
        return
    username, password = context.args
    password_hash = hash_password(password)
    telegram_id = update.message.from_user.id

    try:
        with sqlite3.connect('users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT email, is_verified FROM users WHERE telegram_id = ? AND username = ? AND password_hash = ?',
                          (telegram_id, username, password_hash))
            user = cursor.fetchone()
            if user:
                email, is_verified = user
                if is_verified:
                    cursor.execute('UPDATE users SET is_logged_in = 1 WHERE telegram_id = ?', (telegram_id,))
                    conn.commit()
                    await update.message.reply_text('Login successful!')
                else:
                    otp = generate_otp()
                    store_otp(email, otp)
                    if send_otp_email(email, otp):
                        await update.message.reply_text('An OTP has been sent to your email. Please verify using /verify_otp.')
                    else:
                        await update.message.reply_text('Failed to send OTP. Please try again later.')
            else:
                await update.message.reply_text('Invalid username or password')
    except Exception as e:
        await handle_error(update, "An error occurred during login.", e)

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.message.from_user.id
    try:
        with sqlite3.connect('users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET is_logged_in = 0 WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
        await update.message.reply_text('Logout successful!')
    except Exception as e:
        await handle_error(update, "An error occurred during logout.", e)

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 3:
        await update.message.reply_text('Usage: /delete <username> <password> <email>')
        return
    username, password, email = context.args
    password_hash = hash_password(password)
    telegram_id = update.message.from_user.id

    try:
        with sqlite3.connect('users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ? AND username = ? AND email = ? AND password_hash = ?',
                          (telegram_id, username, email, password_hash))
            if cursor.fetchone():
                cursor.execute('DELETE FROM users WHERE telegram_id = ? AND username = ? AND email = ? AND password_hash = ?',
                              (telegram_id, username, email, password_hash))
                conn.commit()
                if send_delete_mail(username, email):
                    await update.message.reply_text('Your account has been successfully deleted. A confirmation email has been sent.')
                else:
                    await update.message.reply_text('Failed to send confirmation email. You may receive it shortly.')
            else:
                await update.message.reply_text('Invalid credentials. Please check your username, password, and email.')
    except Exception as e:
        await handle_error(update, "An error occurred during account deletion.", e)

async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /stock <stock symbol (i.e., stockname.BO for Indian stock or stocksymbol for global)>')
        return
    symbol = context.args[0]
    price, error = fetch_stock_price(symbol)
    if error:
        await update.message.reply_text(error)
    else:
        await update.message.reply_text(f"The current price of {symbol} is ₹{price}")

async def forex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text('Usage: /forex <from> <to>')
        return
    pair_from, pair_to = context.args
    rate, error = fetch_forex_rate(pair_from, pair_to)
    if error:
        await update.message.reply_text(error)
    else:
        await update.message.reply_text(f"The current exchange rate from {pair_from} to {pair_to} is ₹{rate}")

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = "Live Market Updates:\n\n"
    try:
        stocks_worldwide = get_top_stocks_worldwide()
        stocks_india = get_top_stocks_india()
        forex_prices = get_forex_prices()

        message += "Top Stocks Worldwide:\n" if stocks_worldwide else "No data available for top worldwide stocks.\n\n"
        for stock in stocks_worldwide:
            message += f"{stock['name']}: ₹{stock['current_price']}\n"

        message += "\nTop Stocks in India:\n" if stocks_india else "\nNo data available for top Indian stocks.\n\n"
        for stock in stocks_india:
            message += f"{stock['name']}: ₹{stock['current_price']}\n"

        message += "\nForex Prices:\n" if forex_prices else "\nNo data available for forex prices.\n\n"
        for pair, price in forex_prices.items():
            if price:
                message += f"{pair}: ₹{price}\n"

        await update.message.reply_text(message)
    except Exception as e:
        await handle_error(update, "An unexpected error occurred.", e)

async def budget_highlights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    highlights = "\n\n".join(BUDGET_HIGHLIGHTS)
    await update.message.reply_text(f"Here are the highlights of the 2024 India Budget:\n\n{highlights}", parse_mode="Markdown")

async def finance_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = pyshorteners.Shortener()
    params = {'category': 'business', 'country': 'in', 'apiKey': NEWS_API_KEY}
    try:
        response = requests.get(NEWS_API_URL, params=params)
        data = response.json()
        if data.get('status') == 'ok' and data.get('articles'):
            for article in data['articles']:
                title = escape_markdown_v2(article.get('title', 'No Title'))
                description = escape_markdown_v2(article.get('description', 'No Description'))
                url = s.tinyurl.short(article.get('url', 'No URL'))
                formatted_article = f"**{title}**\n*{description}*\n[Read more]({url})\n"
                await context.bot.send_message(chat_id=update.message.chat_id, text=formatted_article, parse_mode="MarkdownV2")
        else:
            await update.message.reply_text("No news articles found.")
    except Exception as e:
        await handle_error(update, "Failed to fetch news.", e)

async def request_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /request_otp <email>')
        return
    email = context.args[0]
    otp = generate_otp()
    if send_otp_email(email, otp):
        store_otp(email, otp)
        await update.message.reply_text('An OTP has been sent to your email. Please use /verify_otp to verify it.')
    else:
        await update.message.reply_text('Failed to send OTP. Please try again later.')

async def verify_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text('Usage: /verify_otp <email> <otp>')
        return
    email, otp = context.args
    if verify_otp(email, otp):
        try:
            with sqlite3.connect('users.db') as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET is_logged_in = 1 WHERE telegram_id = ?', (update.message.from_user.id,))
                conn.commit()
            await update.message.reply_text('OTP verified successfully. You can now use /recover_username or /reset_password.')
        except Exception as e:
            await handle_error(update, "An error occurred while updating the database.", e)
    else:
        await update.message.reply_text('Invalid or expired OTP. Please try again.')

async def recover_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /recover_username <email>')
        return
    email = context.args[0]
    try:
        with sqlite3.connect('users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT is_logged_in, username FROM users WHERE email = ?', (email,))
            result = cursor.fetchone()
            if result and result[0] == 1:
                await update.message.reply_text(f'Your username is {result[1]}.')
            else:
                await update.message.reply_text('Please verify your email by using /request_otp.')
    except Exception as e:
        await handle_error(update, "An error occurred while accessing the database.", e)

async def reset_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text('Usage: /reset_password <email> <new_password>')
        return
    email, new_password = context.args
    new_password_hash = hash_password(new_password)
    try:
        with sqlite3.connect('users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT is_logged_in FROM users WHERE email = ?', (email,))
            result = cursor.fetchone()
            if result and result[0] == 1:
                cursor.execute('UPDATE users SET password_hash = ? WHERE email = ?', (new_password_hash, email))
                conn.commit()
                await update.message.reply_text('Your password has been reset successfully.')
            else:
                await update.message.reply_text('Please verify your email by using /request_otp.')
    except Exception as e:
        await handle_error(update, "An error occurred while accessing the database.", e)

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /predict <stock symbol>\nExample: /predict RELIANCE.BO or /predict AAPL')
        return
    ticker = context.args[0].upper()
    latest_prices = get_latest_stock_prices(ticker)
    if latest_prices is None:
        await update.message.reply_text(f"Couldn't fetch data for {ticker}. Please check the symbol and try again.")
        return
    try:
        latest_prices_reshaped = np.array(latest_prices).reshape(1, -1)
        predicted_return = model.predict(latest_prices_reshaped)[0]
        await update.message.reply_text(f"The predicted return for {ticker} is {predicted_return:.2%}")
    except Exception as e:
        await handle_error(update, "An error occurred during prediction.", e)

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        name = ' '.join(context.args).lower()
        result = df[df['name'].str.lower().str.contains(name)]
        if not result.empty:
            stocks = [get_stock_details(stock_info['symbol']) for _, stock_info in result.iterrows()]
            message = "\n\n".join(['\n'.join([f"{key}: {value}" for key, value in details.items()]) for details in stocks])
        else:
            message = "Stock not found by that name."
    else:
        message = "Please provide a stock name after the command."
    await update.message.reply_text(message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    response = getgeminiresponse(update.message.text)
    await update.message.reply_text(response)

def getgeminiresponse(input_text, blog_style='Common People'):
    headers = {'Content-Type': 'application/json'}
    data = {
        "prompt": {"text": f"Write a response in the style of a {blog_style} for the topic '{input_text}'."},
        "temperature": 0.01,
        "maxOutputTokens": 256,
    }
    try:
        response = requests.post(GEMINI_URL, headers=headers, json=data)
        if response.status_code == 200:
            return response.json().get('candidates', [{}])[0].get('content', 'No content generated.')
        return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        logger.error(f"Error in Gemini API call: {str(e)}")
        return "An error occurred while generating response."

# --- Main Application ---
def main():
    global df, model
    df = pd.read_csv('stocks.csv')
    ticker = 'AAPL'
    features, labels = download_and_preprocess_data(ticker)
    model = train_model(features, labels)

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('coin', coin))
    application.add_handler(CommandHandler('market', market))
    application.add_handler(CommandHandler('register', register))
    application.add_handler(CommandHandler('login', login))
    application.add_handler(CommandHandler('logout', logout))
    application.add_handler(CommandHandler('delete', delete))
    application.add_handler(CommandHandler('forex', forex))
    application.add_handler(CommandHandler('stock', stock))
    application.add_handler(CommandHandler('budget_highlights', budget_highlights))
    application.add_handler(CommandHandler('finance_news', finance_news))
    application.add_handler(CommandHandler('request_otp', request_otp))
    application.add_handler(CommandHandler('verify_otp', verify_otp))
    application.add_handler(CommandHandler('recover_username', recover_username))
    application.add_handler(CommandHandler('reset_password', reset_password))
    application.add_handler(CommandHandler('predict', predict))
    application.add_handler(CommandHandler('search', search))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    load_dotenv()
    init_database()
    main()
