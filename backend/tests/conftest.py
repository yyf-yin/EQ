import os

# Tests never reach live market data; the AKShare path is covered with a fake module.
os.environ.setdefault('CDR_MARKET_DATA', 'false')
