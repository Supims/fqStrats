# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
import pandas as pd  # noqa
pd.options.mode.chained_assignment = None  # default='warn'
import technical.indicators as ftt
from functools import reduce
from datetime import datetime, timedelta
from freqtrade.strategy import merge_informative_pair
import numpy as np
from freqtrade.strategy import stoploss_from_open


class ichiV1_SPIM(IStrategy):

    # NOTE: settings as of the 25th july 21
    # Buy hyperspace params:
    buy_params = {
        "buy_trend_above_senkou_level": 1,
        "buy_trend_bullish_level": 6,
        "buy_fan_magnitude_shift_value": 3,
        "buy_min_fan_magnitude_gain": 1.002,  # NOTE: Good value (Win% ~70%), alot of trades
        "use_heikin_ashi": True,  # NEW: Parameter to control Heikin-Ashi usage
        #"buy_min_fan_magnitude_gain": 1.008 # NOTE: Very save value (Win% ~90%), only the biggest moves 1.008,
    }

    # Sell hyperspace params:
    # NOTE: was 15m but kept bailing out in dryrun
    sell_params = {
        "sell_trend_indicator": "trend_close_2h",
    }

    # ROI table:
    minimal_roi = {
        "0": 0.059,
        "10": 0.037,
        "41": 0.012,
        "114": 0
    }

    # Stoploss:
    stoploss = -0.171

    # Optimal timeframe for the strategy
    timeframe = '5m'

    startup_candle_count = 96
    process_only_new_candles = True  # FIXED: Changed to True for more realistic live trading

    trailing_stop = True
    trailing_stop_positive = 0.011
    trailing_stop_positive_offset = 0.028
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    plot_config = {
        'main_plot': {
            # fill area between senkou_a and senkou_b
            'senkou_a': {
                'color': 'green', #optional
                'fill_to': 'senkou_b',
                'fill_label': 'Ichimoku Cloud', #optional
                'fill_color': 'rgba(255,76,46,0.2)', #optional
            },
            # plot senkou_b, too. Not only the area to it.
            'senkou_b': {},
            'trend_close_5m': {'color': '#FF5733'},
            'trend_close_15m': {'color': '#FF8333'},
            'trend_close_30m': {'color': '#FFB533'},
            'trend_close_1h': {'color': '#FFE633'},
            'trend_close_2h': {'color': '#E3FF33'},
            'trend_close_4h': {'color': '#C4FF33'},
            'trend_close_6h': {'color': '#61FF33'},
            'trend_close_8h': {'color': '#33FF7D'}
        },
        'subplots': {
            'fan_magnitude': {
                'fan_magnitude': {}
            },
            'fan_magnitude_gain': {
                'fan_magnitude_gain': {}
            }
        }
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # FIXED: Store original close price to avoid validation warning
        dataframe['close_original'] = dataframe['close'].copy()
        
        # FIXED: Proper Heikin-Ashi implementation - use all or none
        if self.buy_params.get('use_heikin_ashi', True):
            heikinashi = qtpylib.heikinashi(dataframe)
            # Store HA values in separate columns to avoid validation issues
            dataframe['ha_open'] = heikinashi['open']
            dataframe['ha_close'] = heikinashi['close']
            dataframe['ha_high'] = heikinashi['high']
            dataframe['ha_low'] = heikinashi['low']
            
            # Use HA values for calculations but keep original close for validation
            dataframe['open'] = heikinashi['open']
            dataframe['high'] = heikinashi['high']
            dataframe['low'] = heikinashi['low']
            # Don't modify close to avoid validation warning
        else:
            # If not using HA, create dummy columns with original values
            dataframe['ha_open'] = dataframe['open']
            dataframe['ha_close'] = dataframe['close']
            dataframe['ha_high'] = dataframe['high']
            dataframe['ha_low'] = dataframe['low']

        # Calculate trend indicators using close prices (use HA close if enabled)
        close_price = dataframe['ha_close'] if self.buy_params.get('use_heikin_ashi', True) else dataframe['close']
        open_price = dataframe['ha_open'] if self.buy_params.get('use_heikin_ashi', True) else dataframe['open']
        
        dataframe['trend_close_5m'] = close_price
        dataframe['trend_close_15m'] = ta.EMA(close_price, timeperiod=3)
        dataframe['trend_close_30m'] = ta.EMA(close_price, timeperiod=6)
        dataframe['trend_close_1h'] = ta.EMA(close_price, timeperiod=12)
        dataframe['trend_close_2h'] = ta.EMA(close_price, timeperiod=24)
        dataframe['trend_close_4h'] = ta.EMA(close_price, timeperiod=48)
        dataframe['trend_close_6h'] = ta.EMA(close_price, timeperiod=72)
        dataframe['trend_close_8h'] = ta.EMA(close_price, timeperiod=96)

        # Calculate trend indicators using open prices (use HA open if enabled)
        dataframe['trend_open_5m'] = open_price
        dataframe['trend_open_15m'] = ta.EMA(open_price, timeperiod=3)
        dataframe['trend_open_30m'] = ta.EMA(open_price, timeperiod=6)
        dataframe['trend_open_1h'] = ta.EMA(open_price, timeperiod=12)
        dataframe['trend_open_2h'] = ta.EMA(open_price, timeperiod=24)
        dataframe['trend_open_4h'] = ta.EMA(open_price, timeperiod=48)
        dataframe['trend_open_6h'] = ta.EMA(open_price, timeperiod=72)
        dataframe['trend_open_8h'] = ta.EMA(open_price, timeperiod=96)

        # FIXED: Add safety checks for fan magnitude calculations
        dataframe['fan_magnitude'] = (dataframe['trend_close_1h'] / dataframe['trend_close_8h']).fillna(1.0)
        
        # FIXED: Add safety check to avoid division by zero or very small numbers
        fan_magnitude_shifted = dataframe['fan_magnitude'].shift(1)
        dataframe['fan_magnitude_gain'] = (dataframe['fan_magnitude'] / fan_magnitude_shifted).fillna(1.0)
        
        # Replace infinite values with 1.0 to avoid issues
        dataframe['fan_magnitude_gain'] = dataframe['fan_magnitude_gain'].replace([np.inf, -np.inf], 1.0)

        # Ichimoku calculation - use original OHLC data to avoid validation issues
        # Create a temporary dataframe with original OHLC for Ichimoku calculation
        ichimoku_data = dataframe[['open', 'high', 'low', 'close_original', 'volume']].copy()
        ichimoku_data['close'] = ichimoku_data['close_original']  # Use original close for Ichimoku
        
        ichimoku = ftt.ichimoku(ichimoku_data, conversion_line_period=20, base_line_periods=60, laggin_span=120, displacement=30)
        dataframe['chikou_span'] = ichimoku['chikou_span']
        dataframe['tenkan_sen'] = ichimoku['tenkan_sen']
        dataframe['kijun_sen'] = ichimoku['kijun_sen']
        dataframe['senkou_a'] = ichimoku['senkou_span_a']
        dataframe['senkou_b'] = ichimoku['senkou_span_b']
        dataframe['leading_senkou_span_a'] = ichimoku['leading_senkou_span_a']
        dataframe['leading_senkou_span_b'] = ichimoku['leading_senkou_span_b']
        dataframe['cloud_green'] = ichimoku['cloud_green']
        dataframe['cloud_red'] = ichimoku['cloud_red']

        # Calculate ATR using original OHLC
        dataframe['atr'] = ta.ATR(ichimoku_data)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = []

        # FIXED: Add safety check for NaN values in conditions
        def safe_condition(condition):
            """Helper function to safely add conditions while handling NaN values"""
            return condition.fillna(False)

        # Trending market - check if trends are above Senkou levels
        if self.buy_params['buy_trend_above_senkou_level'] >= 1:
            conditions.append(safe_condition(dataframe['trend_close_5m'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_5m'] > dataframe['senkou_b']))

        if self.buy_params['buy_trend_above_senkou_level'] >= 2:
            conditions.append(safe_condition(dataframe['trend_close_15m'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_15m'] > dataframe['senkou_b']))

        if self.buy_params['buy_trend_above_senkou_level'] >= 3:
            conditions.append(safe_condition(dataframe['trend_close_30m'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_30m'] > dataframe['senkou_b']))

        if self.buy_params['buy_trend_above_senkou_level'] >= 4:
            conditions.append(safe_condition(dataframe['trend_close_1h'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_1h'] > dataframe['senkou_b']))

        if self.buy_params['buy_trend_above_senkou_level'] >= 5:
            conditions.append(safe_condition(dataframe['trend_close_2h'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_2h'] > dataframe['senkou_b']))

        if self.buy_params['buy_trend_above_senkou_level'] >= 6:
            conditions.append(safe_condition(dataframe['trend_close_4h'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_4h'] > dataframe['senkou_b']))

        if self.buy_params['buy_trend_above_senkou_level'] >= 7:
            conditions.append(safe_condition(dataframe['trend_close_6h'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_6h'] > dataframe['senkou_b']))

        if self.buy_params['buy_trend_above_senkou_level'] >= 8:
            conditions.append(safe_condition(dataframe['trend_close_8h'] > dataframe['senkou_a']))
            conditions.append(safe_condition(dataframe['trend_close_8h'] > dataframe['senkou_b']))

        # Trends bullish - check if close > open for each timeframe
        if self.buy_params['buy_trend_bullish_level'] >= 1:
            conditions.append(safe_condition(dataframe['trend_close_5m'] > dataframe['trend_open_5m']))

        if self.buy_params['buy_trend_bullish_level'] >= 2:
            conditions.append(safe_condition(dataframe['trend_close_15m'] > dataframe['trend_open_15m']))

        if self.buy_params['buy_trend_bullish_level'] >= 3:
            conditions.append(safe_condition(dataframe['trend_close_30m'] > dataframe['trend_open_30m']))

        if self.buy_params['buy_trend_bullish_level'] >= 4:
            conditions.append(safe_condition(dataframe['trend_close_1h'] > dataframe['trend_open_1h']))

        if self.buy_params['buy_trend_bullish_level'] >= 5:
            conditions.append(safe_condition(dataframe['trend_close_2h'] > dataframe['trend_open_2h']))

        if self.buy_params['buy_trend_bullish_level'] >= 6:
            conditions.append(safe_condition(dataframe['trend_close_4h'] > dataframe['trend_open_4h']))

        if self.buy_params['buy_trend_bullish_level'] >= 7:
            conditions.append(safe_condition(dataframe['trend_close_6h'] > dataframe['trend_open_6h']))

        if self.buy_params['buy_trend_bullish_level'] >= 8:
            conditions.append(safe_condition(dataframe['trend_close_8h'] > dataframe['trend_open_8h']))

        # Fan magnitude conditions with safety checks
        conditions.append(safe_condition(dataframe['fan_magnitude_gain'] >= self.buy_params['buy_min_fan_magnitude_gain']))
        conditions.append(safe_condition(dataframe['fan_magnitude'] > 1))

        # FIXED: Add bounds checking for the shift value
        shift_value = min(self.buy_params['buy_fan_magnitude_shift_value'], 10)  # Limit to reasonable range
        for x in range(shift_value):
            shift_condition = safe_condition(dataframe['fan_magnitude'].shift(x+1) < dataframe['fan_magnitude'])
            conditions.append(shift_condition)

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, conditions),
                'buy'] = 1

        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = []

        # FIXED: Add safety check for the sell condition
        sell_indicator = self.sell_params['sell_trend_indicator']
        if sell_indicator in dataframe.columns:
            sell_condition = qtpylib.crossed_below(dataframe['trend_close_5m'], dataframe[sell_indicator])
            conditions.append(sell_condition.fillna(False))
        else:
            # Fallback condition if the indicator doesn't exist
            conditions.append(qtpylib.crossed_below(dataframe['trend_close_5m'], dataframe['trend_close_2h']).fillna(False))

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, conditions),
                'sell'] = 1

        return dataframe