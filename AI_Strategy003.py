from freqtrade.strategy import IStrategy, Trade
from pandas import DataFrame
from typing import Dict
import talib.abstract as ta
import logging
import requests
import json


class AI_Strategy(IStrategy):
    """AI-driven Freqtrade strategy."""

    # Put open router API keys FROM DIFFERENT ACCOUNTS here (bypass daily ratelimit)
    API_KEYS = [
        "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",
        "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",
        "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",
        "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",
        "",
        "",
    ]
    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    API_MODEL = "deepseek/deepseek-chat-v3-0324:free"

    logger = logging.getLogger(__name__)
    logger.info("AI_Strategy loading...")

    INTERFACE_VERSION = 3 # Strategy interface version
    timeframe = '5m' # Timeframe for the strategy
    can_short = False # Can this strategy go short?
    minimal_roi = {"0": 0.02, "60": 0.01, "180": 0} # Exit immediately after X minutes with X% profit
    stoploss = -0.012 # Exit immediately with 1.2% loss
    trailing_stop = False # False = Fixed stop loss
    process_only_new_candles = True # Process only new candles
    startup_candle_count = 200 # Number of candles the strategy requires before producing valid signals
    buy_at_confidence = 0.8 # Buy at AI confidence level

    order_types = {
        'entry': 'market',          # Market for immediate execution
        'exit': 'market',           # Market for sells (lock in profits)
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }

    # Variables for AI
    current_api_key_index = 0
    crypto_data = {} # Store the data for the AI
    free_usdt = 0
    json_response = None


    def informative_pairs(self):
        """Get pair data for the strategy"""
        #Serve as Init function
        self.crypto_data = {}
        self.json_response = None
        # Get the whitelist pairs and return them
        return [(pair, self.timeframe) for pair in self.dp.current_whitelist()]
    

    def populate_indicators(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Calculate indicators and collect the latest values for AI."""

        if self.crypto_data != {}:
            return dataframe

        # Check if max open trades reached - more efficient way
        if len(Trade.get_trades_proxy(is_open=True)) >= self.config.get('max_open_trades', 3):
            return dataframe

        # Collect the data for the AI
        def get_value(indicator):
            if hasattr(indicator, 'empty') and hasattr(indicator, 'iloc'):
                value = indicator.iloc[-1] if not indicator.empty else None
                if value is not None and isinstance(value, (int, float)):
                    rounded = round(value, 4)
                    formatted = f"{rounded:.4f}".rstrip('0').rstrip('.')
                    return formatted if formatted else "0"
                return value
            elif isinstance(indicator, (int, float)):
                rounded = round(indicator, 4)
                formatted = f"{rounded:.4f}".rstrip('0').rstrip('.')
                return formatted if formatted else "0"
                

        self.free_usdt = self.wallets.get_free('USDT')

        for pair in self.dp.current_whitelist():
            alt_df = self.dp.get_pair_dataframe(pair, self.timeframe)
            base_currency = pair.split('/')[0]
            current_holdings = self.wallets.get_free(base_currency)

            # Collect the data for the AI
            self.crypto_data[pair] = {
                # Wallet information
                'current_holdings': current_holdings,
                # Price information
                'current_price': get_value(alt_df['close']),
                'previous_price_5m': get_value(alt_df['close'].shift(1)),
                'previous_price_10m': get_value(alt_df['close'].shift(2)),
                'previous_price_15m': get_value(alt_df['close'].shift(3)),
                'previous_price_30m': get_value(alt_df['close'].shift(6)),
                'previous_price_45m': get_value(alt_df['close'].shift(9)),
                'previous_price_1h': get_value(alt_df['close'].shift(12)),
                'previous_price_2h': get_value(alt_df['close'].shift(24)),
                'previous_price_3h': get_value(alt_df['close'].shift(36)),
                'previous_price_6h': get_value(alt_df['close'].shift(72)),
                'previous_price_8h': get_value(alt_df['close'].shift(96)),
                'previous_price_12h': get_value(alt_df['close'].shift(144)),
                # Percentage changes
                'change_15m': get_value(((alt_df['close'] - alt_df['close'].shift(3)) / alt_df['close'].shift(3)) * 100),
                'change_30m': get_value(((alt_df['close'] - alt_df['close'].shift(6)) / alt_df['close'].shift(6)) * 100),
                'change_45m': get_value(((alt_df['close'] - alt_df['close'].shift(9)) / alt_df['close'].shift(9)) * 100),
                'change_1h': get_value(((alt_df['close'] - alt_df['close'].shift(12)) / alt_df['close'].shift(12)) * 100),
                'change_2h': get_value(((alt_df['close'] - alt_df['close'].shift(24)) / alt_df['close'].shift(24)) * 100),
                'change_3h': get_value(((alt_df['close'] - alt_df['close'].shift(36)) / alt_df['close'].shift(36)) * 100),
                'change_12h': get_value(((alt_df['close'] - alt_df['close'].shift(144)) / alt_df['close'].shift(144)) * 100),
                'last_available_max': alt_df['high'].max(),
                'last_available_min': alt_df['low'].min(),
                'current_to_max_ratio': get_value(alt_df['close'] / alt_df['high'].max()),
                'current_to_min_ratio': get_value(alt_df['close'] / alt_df['low'].min()),
                # Momentum
                'rsi': get_value(ta.RSI(alt_df, timeperiod=14)),
                'willr': get_value(ta.WILLR(alt_df, timeperiod=14)),
                'cci': get_value(ta.CCI(alt_df, timeperiod=14)),
                'roc': get_value(ta.ROC(alt_df, timeperiod=10)),
                'mom': get_value(ta.MOM(alt_df, timeperiod=10)),
                'ultosc': get_value(ta.ULTOSC(alt_df)),
                'adx': get_value(ta.ADX(alt_df, timeperiod=14)),
                'apo': get_value(ta.APO(alt_df, fastperiod=12, slowperiod=26)),
                'ppo': get_value(ta.PPO(alt_df, fastperiod=12, slowperiod=26)),
                'bop': get_value(ta.BOP(alt_df)),
                # Volatility
                'atr': get_value(ta.ATR(alt_df, timeperiod=14)),
                'natr': get_value(ta.NATR(alt_df, timeperiod=14)),
                'trange': get_value(ta.TRANGE(alt_df)),
                # Trend
                'ema10': get_value(ta.EMA(alt_df, timeperiod=10)),
                'ema20': get_value(ta.EMA(alt_df, timeperiod=20)),
                'ema50': get_value(ta.EMA(alt_df, timeperiod=50)),
                'ema100': get_value(ta.EMA(alt_df, timeperiod=100)),
                'ema200': get_value(ta.EMA(alt_df, timeperiod=200)),
                'sma10': get_value(ta.SMA(alt_df, timeperiod=10)),
                'sma20': get_value(ta.SMA(alt_df, timeperiod=20)),
                'sma50': get_value(ta.SMA(alt_df, timeperiod=50)),
                'sma100': get_value(ta.SMA(alt_df, timeperiod=100)),
                'sma200': get_value(ta.SMA(alt_df, timeperiod=200)),
                'wma20': get_value(ta.WMA(alt_df, timeperiod=20)),
                'dema20': get_value(ta.DEMA(alt_df, timeperiod=20)),
                'tema20': get_value(ta.TEMA(alt_df, timeperiod=20)),
                'trix': get_value(ta.TRIX(alt_df, timeperiod=15)),
                'ht_trendline': get_value(ta.HT_TRENDLINE(alt_df)),
                'sar': get_value(ta.SAR(alt_df)),
                # Volume
                'obv': get_value(ta.OBV(alt_df, alt_df['close'])),
                'adosc': get_value(ta.ADOSC(alt_df, fastperiod=3, slowperiod=10)),
                'ad': get_value(ta.AD(alt_df)),
                'mfi': get_value(ta.MFI(alt_df, timeperiod=14)),
                'chaikin_ad': get_value(ta.AD(alt_df)),
            }
            #for key, value in self.crypto_data[pair].items():
                #self.logger.info(f"{key}: {value}")

        # AI
        prompt = f"""
        You are a cryptocurrency trading AI. Analyze the following market data and provide trading recommendations.

        PORTFOLIO STATUS:
        - Free Capital: ${self.free_usdt:.2f} USDT

        MARKET DATA SUMMARY:
        """
        
        # Add summary of each pair's data
        for pair, data in self.crypto_data.items():
            prompt += f"""
            {pair}:"""
            for index, value in data.items():
                prompt += f"""
                - {index}: {value}"""
        
        prompt += """
        
        INSTRUCTIONS:
        Analyze the market data,
        Try to make the best buy decision for short term,
        The goal is +5% profit in the next hour,
        Provide a JSON response with the following structure:
        {
            "analysis": "Brief and short market analysis (1 line max)",
            "recommendations": [
                {
                    "pair": "BTC/USDT",
                    "reason": "Short explanation for the recommendation (1 line max)",
                    "suggested_amount_usdt": 100.0,
                    "confidence": 0.85,
                },
                ...
            ],
        }
        
        Focus on pairs with strong signals and provide specific, actionable recommend
        Analyse all data, and take the best trades possible, but remember to be very very safe
        Use these analysis parameters:
            - Consider technical indicators
            - Evaluate volume trends and support/resistance levels
            - Apply risk-adjusted position sizing
            - Use small parts of your capital
            - Keep it safe, don't be too aggressive, the goal is to win the maxium amount of trades with +5% profit in the next hour.
        """

        # Ask AI
        def ask_AI(api_key, model):
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}

            try:
                self.logger.info(f"Trying to ask AI for trades...")
                response = requests.post(self.API_URL, headers=headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    response_data = response.json()
                    
                    if 'choices' in response_data and len(response_data['choices']) > 0:
                        ai_content = response_data['choices'][0]['message']['content']
                        try:
                            start_idx = ai_content.find('{')
                            end_idx = ai_content.rfind('}') + 1
                            
                            if start_idx != -1 and end_idx > start_idx:
                                json_str = ai_content[start_idx:end_idx]
                                self.json_response = json.loads(json_str)
                                self.logger.info(f"AI Analysis: {self.json_response.get('analysis', 'No analysis provided')}")
                                
                                recommendations = self.json_response.get('recommendations', [])
                                if recommendations:
                                    self.logger.info(f"AI Recommendations: {len(recommendations)} recommendations received")
                                    for rec in recommendations:
                                        self.logger.info(f"  - {rec.get('pair', 'Unknown')}: {rec.get('reason', 'No reason')} (Confidence: {rec.get('confidence', 0)})")
                                else:
                                    self.logger.info("No trading recommendations from AI")
                            else:
                                self.logger.warning("No JSON found in AI response")

                        except json.JSONDecodeError as e:
                            self.logger.error(f"Failed to parse JSON from AI response: {e}")
                    else:
                        self.logger.error("No choices in AI response")
                        
                elif response.status_code == 429:
                    self.logger.warning(f"Daily rate limit exceeded, for API KEY (index: {self.current_api_key_index})")
                    return True # Need to change API_KEY
                        
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request failed: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")


        if self.current_api_key_index >= len(self.API_KEYS):
            self.current_api_key_index = 0

        for index in range(self.current_api_key_index, len(self.API_KEYS)):
            self.current_api_key_index = index
            if self.API_KEYS[index] == "":
                continue                
            if not ask_AI(self.API_KEYS[index], self.API_MODEL): # No need to change API key
                break

        if self.json_response == None:
            self.logger.warning(f"Not a single valid API key, daily rate limit reached, skipping...")

        return dataframe
    

    def populate_entry_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Define entry signals"""

        if self.json_response is None:
            return dataframe

        recommendations = self.json_response.get('recommendations', [])
        pair_recommendation = None
        
        for rec in recommendations:
            if rec.get('pair') == metadata['pair']:
                pair_recommendation = rec
                break
        
        if pair_recommendation is None:
            return dataframe

        if pair_recommendation.get('confidence', 0) >= self.buy_at_confidence:
            dataframe.loc[dataframe.index[-1], 'buy'] = True
            self.logger.info(f"Buy signal set for {metadata['pair']} with confidence {pair_recommendation.get('confidence', 0)}")

        return dataframe
    

    def populate_exit_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        return dataframe