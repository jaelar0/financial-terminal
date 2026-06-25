
# Financial Terminal TUI 
This project is a terminal-based financial data dashboard built with Python's Textual framework, designed as a free, open-source alternative to expensive platforms like the Bloomberg Terminal. The application runs entirely in the terminal and delivers a modern, responsive, multi-pane interface-complete with live-updating widgets, keyboard-driven navigation, and mouse support. By using python's Textual framework, the application is all rendered in the terminal rather than a browser or desktop GUI. 

Currently, data is sourced from two main libraries: yfinance for real-time and historical market data (quotes, price history, fundamentals, options chains), and edgartools for pulling SEC filings directly from EDGAR, including 10-Ks, 10-Qs, and 8-Ks. 

## Setup 

**Recommend**: Using a python virtual environment before any installations and the use of any terminal emulator that supports rich-text rendering (eg. Ghostty)

Install required libraries via pip:

```
pip install --upgrade -r requirements.txt
```

## Demo

After cloning, run the following command to see the app's current state:

```
python main.py
```

On first use of `fundamentals` screen, you will be asked to input your name and email address. SEC requires an identity string before making EDGAR requests via edgartools.
