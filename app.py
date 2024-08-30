import os
from ithaca import IthacaSDK, Auth
from dotenv import load_dotenv
from datetime import datetime
from logger import logger
import requests
import json

load_dotenv()


CALC_SERVER_ENDPOINT = "https://app.canary.ithacanoemon.tech/api/calc"
ETH_ADDRESS = os.getenv("ETH_ADDRESS")
RSA_KEY = os.getenv("RSA_KEY")

if RSA_KEY:
    formatted_rsa_key = RSA_KEY.replace("\\n", "\n")
    with open("private-key.pem", "w") as f:
        f.write(formatted_rsa_key)


class IthacaMMTrader:
    def __init__(self, eth_address, env_name):
        self.quoters = [1751722211735553, 1753074655467521, 1758482201168897]

        self.sdk = IthacaSDK(eth_address=eth_address, env_name=env_name)
        self.sdk.auth = Auth(self.sdk)

        self.sdk.auth.login_rsa()
        self.orderbook = self.get_orderbook()

    def get_contract(self, payoff, expiry, strike):
        """Return contract ID for payoff, expiry and strike."""
        contracts = self.sdk.protocol.contract_list().get("payload")
        expiry = int(datetime.strptime(expiry, "%Y-%m-%d").strftime("%y%m%d") + "080")
        return next(
            (
                contract.get("contractId")
                for contract in contracts
                if contract["payoff"] == payoff
                and contract["economics"]["expiry"] == expiry
                and contract["economics"]["strike"] == strike
            ),
            None,
        )

    def get_orderbook(self) -> list:
        """Return current orderbook."""
        self.sdk.auth.login_rsa()
        orderbook = self.sdk.protocol.orderbook().get("payload")

        orders = list(filter(lambda x: x["clientId"] not in self.quoters, orderbook))
        return orders

    def get_new_trades(self) -> list:
        """Return new orderbook trades."""

        logger.info("--- Starting get_new_trades ---")

        new_orderbook = self.get_orderbook()

        old_order_ids = [order["orderId"] for order in self.orderbook]
        # logger.info(f"Old order IDs: {old_order_ids}")

        new_order_ids = [order["orderId"] for order in new_orderbook]
        # logger.info(f"New order IDs: {new_order_ids}")

        new_ids = [
            order_id for order_id in new_order_ids if order_id not in old_order_ids
        ]
        logger.info(f"Updated Order IDs: {new_ids}")

        new_orders = list(filter(lambda x: x["orderId"] in new_ids, new_orderbook))
        #logger.info(f"New orders to send: {new_orders}")

        self.orderbook = new_orderbook
        #logger.info(f"Orderbook updated: {self.orderbook}")

        logger.info("--- Ending get_new_trades ---")

        return new_orders

    def get_model_price(self, details):
        payload = [
            {
                "orderId": 0,
                "details": [
                    {
                        "currencyPair": row["contractDto"]["economics"]["currencyPair"],
                        "payoff": row["contractDto"]["payoff"],
                        "expiry": row["contractDto"]["economics"]["expiry"],
                        "strike": int(row["contractDto"]["economics"].get("strike")),
                        "position": row["originalQty"]
                        * (1 if row["side"] == "BUY" else -1),
                    }
                    for row in details
                ],
            }
        ]
        res = requests.post(f"{CALC_SERVER_ENDPOINT}/trade_pricer", json=payload)
        if res.status_code == 200:
            try:
                return res.json()[0].get("price")
            except Exception as e:
                logger.error(f"Failed to parse response: {e}")
                return None
        else:
            logger.error(f"Failed to request to Calc Server: {res.status_code}")

    def parse_order(self, order):
        def leg2str(leg):
            details = leg["contractDto"]
            side = 1 if leg["side"] == "BUY" else -1
            qty = float(leg["remainingQty"]) * side
            strike = details["economics"]["strike"]
            # logger.debug(f"Leg details: {details}, Qty: {qty}, Strike: {strike}")
            return f"{qty:+.3f}x{details['payoff']}@{strike:.0f}"

        logger.info("Parsing order started")
        try:
            expiry = datetime.strptime(
                str(order["details"][0]["contractDto"]["economics"]["expiry"]),
                "%y%m%d%H%M",
            ).strftime("%d%b")
            # logger.debug(f"Expiry parsed: {expiry}")
        except Exception as e:
            logger.error(f"Error parsing expiry: {e}")
            logger.debug(f"Order data: {order}")
            return None

        try:
            legs = [leg2str(leg) for leg in order["details"]]
            # logger.debug(f"Legs parsed: {legs}")
        except Exception as e:
            logger.error(f"Error parsing legs: {e}")
            logger.debug(f"Order data: {order}")
            return None

        try:
            model_price = self.get_model_price(order["details"])
            # logger.debug(f"Model price: {model_price}")
        except Exception as e:
            logger.error(f"Error getting model price: {e}")
            logger.debug(f"Order details: {order['details']}")
            model_price = None

        try:
            if model_price:
                msg = f"{order['orderDescr']}, {expiry} | {' '.join(legs)} | px: {order['netPrice']} | model: {model_price:,.2f}"
            else:
                msg = f"{order['orderDescr']}, {expiry} | {' '.join(legs)} | px: {order['netPrice']}"
        except Exception as e:
            logger.error(f"Error creating message: {e}")
            logger.debug(f"Order data: {order}")
            return None

        side = "BUY" if order['netPrice'] > 0 else "SELL"
        isTrade = side == "BUY" and order['netPrice'] > model_price or side == "SELL" and order['netPrice'] < model_price
        return msg, isTrade

    def send_order(self, order):
        """Send order to Ithaca."""
        self.sdk.auth.login_rsa()
        legs = [(leg['contractId'], 'BUY' if leg['side'] == "SELL" else "SELL", leg['remainingQty']) for leg in order["details"]]
        price = -order['netPrice']
        res = self.sdk.orders.new_order(legs=legs, price=price)
        logger.info(f"Order sent: {res}")

    def handler(self, ws, msg):
        data = json.loads(msg)
        response = data.get("responseType")

        match response:
            case "VALIDATE_AUTH_TOKEN_RESPONSE":
                logger.info("Auth token validated")

            case "AUCTION_STARTED":
                logger.info("Auction started")

            case "AUCTION_FINISHED":
                logger.info("Auction finished")

            case "TRADE_REPORT":
                logger.info(data)

            case "EXEC_REPORT":
                logger.info(data)

            case "MM_ORDERBOOK_UPDATED":
                logger.info("MM_ORDERBOOK_UPDATED")
                new_trades = self.get_new_trades()

                for trade in new_trades:
                    msg, isTrade = self.parse_order(trade)
                    logger.info(msg)
                    if isTrade:
                        self.send_order(trade)

            case _:
                pass

    def run(self):
        self.sdk.socket.connect(self.handler)


trader = IthacaMMTrader(ETH_ADDRESS, "CANARY")

trader.run()
