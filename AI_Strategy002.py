from freqtrade.strategy import IStrategy
from pandas import DataFrame
from typing import Dict
import talib.abstract as ta
import logging
import requests
import json


class AI_Strategy(IStrategy):
    """AI-driven Freqtrade strategy."""

    # Replace with your actual OpenRouter API key
    API_KEY = "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"
    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    API_MODEL = "deepseek/deepseek-chat-v3-0324:free"

    buy_at_confidence = 0.8 # Buy at confidence level
    
    INTERFACE_VERSION = 3 # Strategy interface version
    timeframe = '5m' # Timeframe for the strategy
    can_short = False # Can this strategy go short?
    minimal_roi = {"0": 0.05, "60": 0.015, "180": 0} # Exit immediately after X minutes with X% profit
    stoploss = -0.02 # Exit immediately with 2% loss
    trailing_stop = False # False = Fixed stop loss
    process_only_new_candles = True # Process only new candles
    startup_candle_count = 200 # Number of candles the strategy requires before producing valid signals
    
    order_types = {
        'entry': 'market',          # Market for immediate execution
        'exit': 'market',           # Market for sells (lock in profits)
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }

    logger = logging.getLogger(__name__)

    free_usdt = 0
    json_response = None
    collected_crypto_data = None # Store the data for the AI


    def informative_pairs(self):
        """Get pair data for the strategy."""
        # Serves as Init function
        self.json_response = None
        self.collected_crypto_data = None

        # Get the whitelist pairs and return them so it loads the data for all pairs and not progressively
        whitelist_pairs = self.dp.current_whitelist()
        return [(pair, self.timeframe) for pair in whitelist_pairs]


    def populate_indicators(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Calculate indicators and collect the latest values for AI."""

        if self.collected_crypto_data != None:
            return dataframe
        
        self.collected_crypto_data = {}
        whitelist_pairs = self.dp.current_whitelist()
        self.logger.info(f"Collecting data for {len(whitelist_pairs)} pairs")

        # Get wallet information
        self.free_usdt = self.wallets.get_free('USDT')

        # Store the latest value for each indicator for this pair
        def last(indicator):
            if indicator is None:
                return None
            elif isinstance(indicator, str):
                return indicator
            elif hasattr(indicator, 'empty') and hasattr(indicator, 'iloc'):
                value = indicator.iloc[-1] if not indicator.empty else None
                if value is not None and isinstance(value, (int, float)):
                    # Round to 3 decimal places and remove trailing zeros
                    rounded = round(value, 4)
                    # Convert to string and remove trailing zeros after decimal point
                    formatted = f"{rounded:.4f}".rstrip('0').rstrip('.')
                    return formatted if formatted else "0"
                return value
            else:
                if isinstance(indicator, (int, float)):
                    # Round to 3 decimal places and remove trailing zeros
                    rounded = round(indicator, 4)
                    formatted = f"{rounded:.4f}".rstrip('0').rstrip('.')
                    return formatted if formatted else "0"
                return indicator

        for pair in whitelist_pairs:
            alt_df = self.dp.get_pair_dataframe(pair, self.timeframe)

            base_currency = pair.split('/')[0]
            current_holdings = self.wallets.get_free(base_currency)

            # Collect the data for the AI
            self.collected_crypto_data[pair] = {
                # Wallet information
                'current_holdings': current_holdings,
                # Price information
                'current_price': last(alt_df['close']),
                'previous_price_5m': last(alt_df['close'].shift(1)),
                'previous_price_10m': last(alt_df['close'].shift(2)),
                'previous_price_15m': last(alt_df['close'].shift(3)),
                'previous_price_30m': last(alt_df['close'].shift(6)),
                'previous_price_45m': last(alt_df['close'].shift(9)),
                'previous_price_1h': last(alt_df['close'].shift(12)),
                'previous_price_2h': last(alt_df['close'].shift(24)),
                'previous_price_3h': last(alt_df['close'].shift(36)),
                'previous_price_6h': last(alt_df['close'].shift(72)),
                'previous_price_8h': last(alt_df['close'].shift(96)),
                'previous_price_12h': last(alt_df['close'].shift(144)),
                # Percentage changes
                'change_15m': last(((alt_df['close'] - alt_df['close'].shift(3)) / alt_df['close'].shift(3)) * 100),
                'change_30m': last(((alt_df['close'] - alt_df['close'].shift(6)) / alt_df['close'].shift(6)) * 100),
                'change_45m': last(((alt_df['close'] - alt_df['close'].shift(9)) / alt_df['close'].shift(9)) * 100),
                'change_1h': last(((alt_df['close'] - alt_df['close'].shift(12)) / alt_df['close'].shift(12)) * 100),
                'change_2h': last(((alt_df['close'] - alt_df['close'].shift(24)) / alt_df['close'].shift(24)) * 100),
                'change_3h': last(((alt_df['close'] - alt_df['close'].shift(36)) / alt_df['close'].shift(36)) * 100),
                'change_12h': last(((alt_df['close'] - alt_df['close'].shift(144)) / alt_df['close'].shift(144)) * 100),
                'last_available_max': alt_df['high'].max(),
                'last_available_min': alt_df['low'].min(),
                'current_to_max_ratio': last(alt_df['close'] / alt_df['high'].max()),
                'current_to_min_ratio': last(alt_df['close'] / alt_df['low'].min()),
                # Momentum
                'rsi': last(ta.RSI(alt_df, timeperiod=14)),
                'willr': last(ta.WILLR(alt_df, timeperiod=14)),
                'cci': last(ta.CCI(alt_df, timeperiod=14)),
                'roc': last(ta.ROC(alt_df, timeperiod=10)),
                'mom': last(ta.MOM(alt_df, timeperiod=10)),
                'ultosc': last(ta.ULTOSC(alt_df)),
                'adx': last(ta.ADX(alt_df, timeperiod=14)),
                'apo': last(ta.APO(alt_df, fastperiod=12, slowperiod=26)),
                'ppo': last(ta.PPO(alt_df, fastperiod=12, slowperiod=26)),
                'bop': last(ta.BOP(alt_df)),
                # Volatility
                'atr': last(ta.ATR(alt_df, timeperiod=14)),
                'natr': last(ta.NATR(alt_df, timeperiod=14)),
                'trange': last(ta.TRANGE(alt_df)),
                # Trend
                'ema10': last(ta.EMA(alt_df, timeperiod=10)),
                'ema20': last(ta.EMA(alt_df, timeperiod=20)),
                'ema50': last(ta.EMA(alt_df, timeperiod=50)),
                'ema100': last(ta.EMA(alt_df, timeperiod=100)),
                'ema200': last(ta.EMA(alt_df, timeperiod=200)),
                'sma10': last(ta.SMA(alt_df, timeperiod=10)),
                'sma20': last(ta.SMA(alt_df, timeperiod=20)),
                'sma50': last(ta.SMA(alt_df, timeperiod=50)),
                'sma100': last(ta.SMA(alt_df, timeperiod=100)),
                'sma200': last(ta.SMA(alt_df, timeperiod=200)),
                'wma20': last(ta.WMA(alt_df, timeperiod=20)),
                'dema20': last(ta.DEMA(alt_df, timeperiod=20)),
                'tema20': last(ta.TEMA(alt_df, timeperiod=20)),
                'trix': last(ta.TRIX(alt_df, timeperiod=15)),
                'ht_trendline': last(ta.HT_TRENDLINE(alt_df)),
                'sar': last(ta.SAR(alt_df)),
                # Volume
                'obv': last(ta.OBV(alt_df, alt_df['close'])),
                'adosc': last(ta.ADOSC(alt_df, fastperiod=3, slowperiod=10)),
                'ad': last(ta.AD(alt_df)),
                'mfi': last(ta.MFI(alt_df, timeperiod=14)),
                'chaikin_ad': last(ta.AD(alt_df)),
            }

            #for key, value in self.collected_crypto_data[pair].items():
                #self.logger.info(f"{key}: {value}")
            
        # Ask AI
        self.logger.info(f"Asking AI for trades")

        prompt = f"""
        You are a cryptocurrency trading AI. Analyze the following market data and provide trading recommendations.

        PORTFOLIO STATUS:
        - Free Capital: ${self.free_usdt:.2f} USDT

        MARKET DATA SUMMARY:
        """
        
        # Add summary of each pair's data
        for pair, data in self.collected_crypto_data.items():
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
        
        Focus on pairs with strong signals and provide specific, actionable recommendations.
        Use these analysis parameters:
            - Consider technical indicators
            - Evaluate volume trends and support/resistance levels
            - Apply risk-adjusted position sizing
            - Keep it safe, don't be too aggressive, the goal is to win the maxium amount of trades with +5% profit in the next hour.
        """

        if not self.API_KEY or self.API_KEY == "":
            self.logger.error(f"API_KEY is not set")
            return dataframe

        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.API_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        try:
            # Make the API request
            response = requests.post(self.API_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Extract the content from the AI response
                if 'choices' in response_data and len(response_data['choices']) > 0:
                    ai_content = response_data['choices'][0]['message']['content']
                    
                    # Try to parse the JSON response from the AI
                    try:
                        # Find JSON in the response (in case AI includes extra text)
                        start_idx = ai_content.find('{')
                        end_idx = ai_content.rfind('}') + 1
                        
                        if start_idx != -1 and end_idx > start_idx:
                            json_str = ai_content[start_idx:end_idx]
                            self.json_response = json.loads(json_str)
                            
                            self.logger.info(f"AI Analysis: {self.json_response.get('analysis', 'No analysis provided')}")
                            
                            # Log recommendations
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
                        self.logger.info(f"Raw AI response: {ai_content}")
                else:
                    self.logger.error("No choices in AI response")
                    
            else:
                self.logger.error(f"API request failed with status code: {response.status_code}")
                self.logger.error(f"Response: {response.text}")
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request failed: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Define entry signals"""

        if self.json_response is None:
            return dataframe

        # Find recommendation for this pair
        recommendations = self.json_response.get('recommendations', [])
        pair_recommendation = None
        
        for rec in recommendations:
            if rec.get('pair') == metadata['pair']:
                pair_recommendation = rec
                break
        
        if pair_recommendation is None:
            return dataframe

        # Check confidence and set buy signal
        if pair_recommendation.get('confidence', 0) >= self.buy_at_confidence:
            # Set buy signal to True (not the amount - Freqtrade expects boolean)
            dataframe.loc[dataframe.index[-1], 'buy'] = True
            self.logger.info(f"Buy signal set for {metadata['pair']} with confidence {pair_recommendation.get('confidence', 0)}")

        return dataframe


    def populate_exit_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Define exit signals"""
        return dataframe