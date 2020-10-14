'''
VERSION 1.0 (Under Construction)
- Risk/reward will be adjusted to remove 2% upside cap
  Trades in profit at atrx2 and above will use histogram value thresholds to take profits
- Firm stop will be shifted up again at atrx2 to atrx0.5 & at atrx4 to atrx2.5
- Added failsafes and optimisation prior to Go Live on a demo account


VERSION 0.1 (2 Oct 2020)
- Basic risk/reward of 1.5:2 
- Max downside risk of 1.5%
- Initial stop placed at atrx1.5
- Adjusts stop to breakeven when in profit atrx1.5
- Stop repositions to break-even when atrx1.5 is hit when ATR > 15 (AUDUSD)*
- All profits are capped and taken at atrx2
- When position is closed all outstanding orders are cancelled
- Trades taken against the baseline have a MACD signal line threshold of 20 (AUDUSD)*
- Volatility failsafes: 2 (Max bar range & ATR thresholds)

* All dictionaries will require updating for new ccy pairs
'''

from QuantConnect import *
from QuantConnect.Algorithm import *
from QuantConnect.Indicators import *
from QuantConnect.Data.Consolidators import *
from datetime import date, datetime, timedelta
import math

class PenskeFile(QCAlgorithm):
    
    def Initialize(self):
    
        # Setting main strategy parameters

        self.SetTimeZone(TimeZones.Utc)                                  # Sets settings to UTC time (-10 from AEST)
        #self.SetStartDate(date.today()-timedelta(days = 35))
        #self.SetEndDate(date.today()-timedelta(days = 1))
        self.SetStartDate(2018, 1, 16)
        self.SetEndDate(2018, 3, 1) 
        self.SetCash(10000)
        self.SetBrokerageModel(BrokerageName.OandaBrokerage)             # Configures Oanda fees, fill & slippage models
        self.SetWarmup(100)

        # Securities to be traded

        self.ccypair = "AUDUSD"                                          # For XAU pairs use .AddCfd
        self.AddForex(self.ccypair, Resolution.Hour, Market.Oanda)
        self.SetBenchmark(self.ccypair)
        
        if self.ccypair[-3:] == 'JPY':
            self.PriceRounding = 3
        else:
            self.PriceRounding = 5

        # Consolidation price data into four hour quote bars
        
        FourHours = QuoteBarConsolidator(timedelta(hours=4))
        FourHours.DataConsolidated += self.FourHourBarHandler
        self.SubscriptionManager.AddConsolidator(self.ccypair, FourHours)
        
        # Core indicator variables (4 hour EMA, ATR & MACD)

        ema = self.EMA(self.ccypair, 100, Resolution.Hour)
        self.H4ema = ExponentialMovingAverage(100)
        self.RegisterIndicator(self.ccypair, self.H4ema, timedelta(hours=4))
        
        atr = self.ATR(self.ccypair, 14, MovingAverageType.Exponential, Resolution.Hour)
        self.H4atr = AverageTrueRange(14)
        self.RegisterIndicator(self.ccypair, self.H4atr, timedelta(hours=4))
        
        macd = self.MACD(self.ccypair, 12, 26, 9, MovingAverageType.Exponential, Resolution.Hour)
        self.H4macd = MovingAverageConvergenceDivergence(12,26,9)
        self.RegisterIndicator(self.ccypair, self.H4macd, timedelta(hours=4))
        
        self.SubscriptionManager.AddConsolidator(self.ccypair, FourHours)
        self.GreenLight = 'N'
        self.HighHistThreshold = 'N'
        self.AdjustStop = 0
        
        # Indicator extensions
        
        # Main Long trigger (1)
        self.workings1 = IndicatorExtensions.Times(self.H4atr, 0.1)
        self.goLong = IndicatorExtensions.Minus(self.H4macd.Histogram, self.workings1)
        
        # Main Short trigger (2)
        self.workings2 = IndicatorExtensions.Times(self.H4atr, -0.1)
        self.goShort = IndicatorExtensions.Minus(self.workings2, self.H4macd.Histogram)
        
        # Against baseline & Long additional signal line trigger (3)
        self.workings3a = IndicatorExtensions.Times(self.H4macd.Signal, -1)
        self.workings3b = IndicatorExtensions.Times(self.H4atr, 1)
        self.signalLong = IndicatorExtensions.Minus(self.workings3a, self.workings3b)
        
        # Against baseline & Short additional signal line trigger (4)
        self.workings4 = IndicatorExtensions.Times(self.H4atr, 1)
        self.signalShort = IndicatorExtensions.Minus(self.H4macd.Signal, self.workings4)
        
        # Create rolling windows
        
        self.window = RollingWindow[QuoteBar](3)
        
        self.H4emaWindow = RollingWindow[float](3)
        self.H4atrWindow = RollingWindow[float](3)
        self.H4macdWindow = RollingWindow[float](3)
        self.H4MACDhistogramWindow = RollingWindow[float](3)
        self.H4MACDsignalWindow = RollingWindow[float](3)
        
        self.goLongWindow = RollingWindow[float](3)
        self.goShortWindow = RollingWindow[float](3)
        self.signalLongWindow = RollingWindow[float](3)
        self.signalShortWindow = RollingWindow[float](3)
        
    def FourHourBarHandler(self, sender, QuoteBar):
        self.window.Add(QuoteBar)
    
    def OnData(self, data):

        # Update rolling windows
        
        self.H4emaWindow.Add(self.H4ema.Current.Value)      
        self.H4atrWindow.Add(self.H4atr.Current.Value)
        self.H4macdWindow.Add(self.H4macd.Current.Value)
        self.H4MACDhistogramWindow.Add(self.H4macd.Histogram.Current.Value)
        self.H4MACDsignalWindow.Add(self.H4macd.Signal.Current.Value)
        
        self.goLongWindow.Add(self.goLong.Current.Value)
        self.goShortWindow.Add(self.goShort.Current.Value)
        self.signalLongWindow.Add(self.signalLong.Current.Value)
        self.signalShortWindow.Add(self.signalShort.Current.Value)
        
        # Data checks - everything ready?
        
        if self.IsWarmingUp: return
        if not (self.H4ema.IsReady and self.H4macd.IsReady and self.H4atr.IsReady) : return
        if not (self.window.IsReady and self.H4emaWindow.IsReady and \
        self.H4atrWindow.IsReady and self.H4macdWindow.IsReady and self.H4MACDhistogramWindow.IsReady \
        and self.goLongWindow.IsReady and self.goShortWindow.IsReady and self.signalLongWindow.IsReady \
        and self.signalShortWindow.IsReady and self.H4MACDsignalWindow.IsReady): return
    
        currBar = self.window[0]
        pastBar = self.window[1]
        self.barRangePct = (currBar.High - currBar.Low) / currBar.Open
        self.barReversalLong = (currBar.High - currBar.Close) / currBar.High
        self.barReversalShort = (currBar.Close - currBar.Low) / currBar.Low
        
        # Risk management variables/targets (Set at 1.5% risk on each trade) + Assoc. rolling windows
        
        self.LossRisk = 0.015
        self.DownsideRisk = 1.5
        self.UpsideRisk = 2
        self.atrMultiplier = round(self.H4atrWindow[0] * 10000, 2)
        
        self.Baseline = round(currBar.Ask.Close - self.H4emaWindow[0], 5)

        # Setting position size (Variable based on % of a/c cash value)
        
        self.TradeRisk = self.Portfolio.Cash * self.LossRisk
        
        if self.ccypair[-3:] == 'JPY':
            self.BuyPositionSize = math.ceil((self.TradeRisk / (self.atrMultiplier * self.DownsideRisk)) * 1000000)
        else:
            self.BuyPositionSize = math.ceil((self.TradeRisk / (self.atrMultiplier * self.DownsideRisk)) * 10000)
        
        self.SellPositionSize = self.BuyPositionSize * -1
        
        # GREEN LIGHT? (Ensures only one trade per MACD histogram signal)
        # Changes the GreenLight value to 'Y' each time the histogram crosses 0. When a trade is
        # entered into, the value changes to 'N'. Trades will not be executed if the 
        # GreenLight value == 'N'.
        
        if self.H4MACDhistogramWindow[1] < 0 and self.H4MACDhistogramWindow[0] > 0:
            self.GreenLight = 'Y'
            self.HighHistThreshold = 'N'
        if self.H4MACDhistogramWindow[1] > 0 and self.H4MACDhistogramWindow[0] < 0:
            self.GreenLight = 'Y'
            self.HighHistThreshold = 'N'
        
        ''' TRADE EXECUTION '''

        if not self.Portfolio.Invested:
            
            # Runs through failsafe checklist
            self.Failsafes()

            XBaseline_Signal_Thresholds = {'AUDUSD': 0.0020, 'GBPJPY': 0.380, 'NZDJPY': 0.2}

            # With Baseline & Long
            if self.GreenLight == 'Y' and self.goLongWindow[1] < 0 and self.goLongWindow[0] > 0 and self.Baseline > 0:
                self.OpenLong()

            # With Baseline & Short
            elif self.GreenLight == 'Y' and self.goShortWindow[1] < 0 and self.goShortWindow[0] > 0 and self.Baseline < 0:
                self.OpenShort()
            
            # Against Baseline & Long
            elif self.GreenLight == 'Y' and self.signalLongWindow[0] > 0 and self.goLongWindow[1] < 0 and\
            self.goLongWindow[0] > 0 and self.Baseline < 0 and self.H4MACDsignalWindow[1] < XBaseline_Signal_Thresholds[self.ccypair] * -1:
                self.OpenLong()

            # Against Baseline & Short
            elif self.GreenLight == 'Y' and self.signalShortWindow[0] > 0 and self.goShortWindow[1] < 0 and\
            self.goShortWindow[0] > 0 and self.Baseline > 0 and self.H4MACDsignalWindow[1] > XBaseline_Signal_Thresholds[self.ccypair]:
                self.OpenShort()
            
        self.ShiftFirmStop()
        self.LetProfitsRun()
        self.CancelOutstandings()
        
        ''' DEBUGGING '''
        
        #self.Debug("Reversal Short: {}".format(self.barReversalShort))
        #self.Debug("Bar Low: {}, Bar Close: {}".format(self.window[0].Low, self.window[0].Close))
        #self.Debug("Green light to trade?: {}, Adjust Stop Value: {}, High Histogram Threshold?: {}".format(self.GreenLight, self.AdjustStop, self.HighHistThreshold))
        #self.Debug("Previous Histogram: {}, Current Histogram: {}".format(round(self.H4MACDhistogramWindow[1],5), round(self.H4MACDhistogramWindow[0],5)))
        #self.Debug("Current ATR: {}, GoL: {} -> {}, GoS: {} -> {}"\
        #.format(round(self.H4atrWindow[0],5), round(self.goLongWindow[1],6), round(self.goLongWindow[0],6)\
        #, round(self.goShortWindow[1],6), round(self.goShortWindow[0],6)))
        #self.Debug("Signal Long: {} -> {}, Signal Short: {} -> {}"\
        #.format(round(self.signalLongWindow[1],6),round(self.signalLongWindow[0],6)\
        #,round(self.signalShortWindow[1],6),round(self.signalShortWindow[0],6)))
        #self.Debug("MACD Signal Line: {}, Signal Window: {}".format(self.H4macd.Signal, self.H4MACDsignalWindow[0]))
        #self.Debug("EMA: {}, Baseline: {}".format(self.H4emaWindow[0], self.Baseline))
        #openOrders = self.Transactions.GetOpenOrders()
        #self.Debug("Open Tickets: {}".format(openOrders))
        #self.Debug("Position: {}".format(self.Portfolio[self.ccypair].HoldingsValue))

        ''' STRATEGY FUNCTIONS '''
    
    def OpenLong(self):
        self.XEntryPrice = self.Securities[self.ccypair].AskPrice
        self.CloseLongPosition = self.BuyPositionSize * -1
        self.MarketOrder(self.ccypair, self.BuyPositionSize)
        self.InitialLongTargets()
        self.AdjustStop = 0
        self.GreenLight = 'N'
        self.sl_order = self.StopMarketOrder(self.ccypair, self.SellPositionSize, self.InitialStopLong, 'SL')

    def OpenShort(self):
        self.XEntryPrice = self.Securities[self.ccypair].BidPrice
        self.CloseShortPosition = self.SellPositionSize * -1
        self.MarketOrder(self.ccypair, self.SellPositionSize)
        self.InitialShortTargets()
        self.AdjustStop = 0
        self.GreenLight = 'N'
        self.sl_order = self.StopMarketOrder(self.ccypair, self.BuyPositionSize, self.InitialStopShort, 'SL')

    def InitialLongTargets(self):
        self.InitialStopLong = round(self.Securities[self.ccypair].Price - (self.H4atrWindow[0] * self.DownsideRisk), self.PriceRounding) #-ATRx1.5
        self.MidStopLong = round(self.XEntryPrice + (self.H4atrWindow[0] * 0.5), self.PriceRounding) #ATRx0.5
        self.FirstTargetLong = round(self.XEntryPrice + (self.H4atrWindow[0] * 1.5), self.PriceRounding) #ATRx1.5
        self.SecondTargetLong = round(self.XEntryPrice + (self.H4atrWindow[0] * self.UpsideRisk), self.PriceRounding) #ATRx2
        self.HighStopLong = round(self.XEntryPrice + (self.H4atrWindow[0] * 2.5), self.PriceRounding) #ATRx2.5
        self.ThirdTargetLong = round(self.XEntryPrice + (self.H4atrWindow[0] * 4), self.PriceRounding) #ATRx4
        self.HugeMoveStopLong = round(self.XEntryPrice + (self.H4atrWindow[0] * 8), self.PriceRounding) #ATRx8
        self.HugeMoveLong = round(self.XEntryPrice + (self.H4atrWindow[0] * 10), self.PriceRounding) #ATRx10
        
    def InitialShortTargets(self):
        self.InitialStopShort = round(self.Securities[self.ccypair].Price + (self.H4atrWindow[0] * self.DownsideRisk), self.PriceRounding)
        self.MidStopShort = round(self.XEntryPrice - (self.H4atrWindow[0] * 0.5), self.PriceRounding)
        self.FirstTargetShort = round(self.XEntryPrice - (self.H4atrWindow[0] * 1.5), self.PriceRounding)
        self.SecondTargetShort = round(self.XEntryPrice - (self.H4atrWindow[0] * self.UpsideRisk), self.PriceRounding)
        self.HighStopShort = round(self.XEntryPrice - (self.H4atrWindow[0] * 2.5), self.PriceRounding)
        self.ThirdTargetShort = round(self.XEntryPrice - (self.H4atrWindow[0] * 4), self.PriceRounding)
        self.HugeMoveStopShort = round(self.XEntryPrice - (self.H4atrWindow[0] * 8), self.PriceRounding)
        self.HugeMoveShort = round(self.XEntryPrice - (self.H4atrWindow[0] * 10), self.PriceRounding)

    def ShiftFirmStop(self):
        
        self.Stop_ATR_Thresholds = {'AUDUSD': 0.0015, 'GBPJPY': 0.35, 'NZDJPY': 0.15}

        # Moving stop when price reaches ATRx1.5 to breakeven

        if self.Portfolio[self.ccypair].IsLong and (self.Securities[self.ccypair].Price > self.FirstTargetLong)\
        and self.H4atrWindow[0] > self.Stop_ATR_Thresholds[self.ccypair] and self.AdjustStop == 0 :
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.XEntryPrice
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1
        
        if self.Portfolio[self.ccypair].IsShort and (self.Securities[self.ccypair].Price < self.FirstTargetShort)\
        and self.H4atrWindow[0] > self.Stop_ATR_Thresholds[self.ccypair] and self.AdjustStop == 0 :
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.XEntryPrice
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1

        # Moving stop again when price reaches ATRx2 to +ATRx0.5
        
        if self.Portfolio[self.ccypair].IsLong and (self.Securities[self.ccypair].Price > self.SecondTargetLong)\
        and self.H4atrWindow[0] > self.Stop_ATR_Thresholds[self.ccypair] and self.AdjustStop == 1:
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.MidStopLong
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1

        if self.Portfolio[self.ccypair].IsShort and (self.Securities[self.ccypair].Price < self.SecondTargetShort)\
        and self.H4atrWindow[0] > self.Stop_ATR_Thresholds[self.ccypair] and self.AdjustStop == 1:
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.MidStopShort
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1
 
        # When profit hits ATRx4 readjust stop again to +ATRx2.5
        # Stop ATR thresholds are removed as at these levels it shouldn't be a factor
        
        if self.Portfolio[self.ccypair].IsLong and (self.Securities[self.ccypair].Price > self.ThirdTargetLong)\
        and self.AdjustStop == 2:
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.HighStopLong
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1

        if self.Portfolio[self.ccypair].IsShort and (self.Securities[self.ccypair].Price < self.ThirdTargetShort)\
        and self.AdjustStop == 2:
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.HighStopShort
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1

        # When profit hits ATRx10 readjust stop again to +ATRx8 (caters for huge sudden moves)
        
        if self.Portfolio[self.ccypair].IsLong and (self.Securities[self.ccypair].Price > self.HugeMoveLong)\
        and self.AdjustStop == 3:
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.HugeMoveStopLong
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1

        if self.Portfolio[self.ccypair].IsShort and (self.Securities[self.ccypair].Price < self.HugeMoveShort)\
        and self.AdjustStop == 3:
            updateFields = UpdateOrderFields()
            updateFields.StopPrice = self.HugeMoveStopShort
            self.sl_order.Update(updateFields)
            self.AdjustStop += 1

    def LetProfitsRun(self):

        self.High_Histogram_Threshold = {'AUDUSD': 0.00100, 'NZDJPY': 0.1}
        self.Mid_Histogram_Threshold = {'AUDUSD': 0.00050, 'NZDJPY': 0.05}
        self.Low_Histogram_Threshold = {'AUDUSD': 0.00020, 'NZDJPY': 0.02}

        if self.Portfolio[self.ccypair].IsLong and self.H4MACDhistogramWindow[0] > self.High_Histogram_Threshold[self.ccypair]:
            self.HighHistThreshold = 'Y'
        elif self.Portfolio[self.ccypair].IsShort and self.H4MACDhistogramWindow[0] < (self.High_Histogram_Threshold[self.ccypair] * -1):
            self.HighHistThreshold = 'Y'

        # Long positions that hit > atr x 2 and High Histogram theshold
        if self.Portfolio[self.ccypair].IsLong and self.Securities[self.ccypair].BidPrice > self.SecondTargetLong:
            if self.HighHistThreshold == 'Y' and self.H4MACDhistogramWindow[0] < self.Mid_Histogram_Threshold[self.ccypair]:
                self.MarketOrder(self.ccypair, self.CloseLongPosition)
                self.Liquidate(self.ccypair)
        # Long positions that hit > atr x 2 and do not hit the High Histogram threshold
            if self.HighHistThreshold == 'N' and self.H4MACDhistogramWindow[0] < self.Low_Histogram_Threshold[self.ccypair]:
                self.MarketOrder(self.ccypair, self.CloseLongPosition)
                self.Liquidate(self.ccypair)

        # Short positions that hit > atr x 2 and High Histogram theshold
        if self.Portfolio[self.ccypair].IsShort and self.Securities[self.ccypair].AskPrice < self.SecondTargetShort:
            if self.HighHistThreshold == 'Y' and self.H4MACDhistogramWindow[0] > (self.Mid_Histogram_Threshold[self.ccypair] * -1):
                self.MarketOrder(self.ccypair, self.CloseShortPosition)
                self.Liquidate(self.ccypair)
        # Short positions that hit > atr x 2 and do not hit the High Histogram threshold
            if self.HighHistThreshold == 'N' and self.H4MACDhistogramWindow[0] > (self.Low_Histogram_Threshold[self.ccypair] * -1):
                self.MarketOrder(self.ccypair, self.CloseShortPosition)
                self.Liquidate(self.ccypair)

    def CancelOutstandings(self):
        if not self.Portfolio[self.ccypair].Invested and self.GreenLight == 'N':
            self.Liquidate(self.ccypair)

    def Failsafes(self):

        self.BarRangeExceeded = 'N'
        self.HighVolWarning = 'N'

        # Will not open trades when the latest completed bar has moved > 3.5% (using highest and lowest prices)
        if self.barRangePct > 0.0350:
            self.GreenLight = 'N'
            self.BarRangeExceeded = 'Y'
        else:
            self.BarRangeExceeded = 'N'

        # Will not open trades when ATR levels exceed certain thresholds. Should only be triggered during
        # periods of extreme volatility

        TradeOpen_ATR_Thresholds = {'AUDUSD': 0.008, 'GBPJPY': 0.9, 'NZDJPY': 0.8}

        if self.H4atrWindow[0] > TradeOpen_ATR_Thresholds[self.ccypair]:
            self.GreenLight = 'N'
            self.HighVolWarning = 'Y'
        else:
            self.HighVolWarning = 'N'

        # Will take profits if the price reverses on the latest completed bar over 2%

        if self.Portfolio[self.ccypair].IsLong and self.barReversalLong > 0.02:
            self.MarketOrder(self.ccypair, self.CloseLongPosition)
            self.Liquidate(self.ccypair)
        elif self.Portfolio[self.ccypair].IsShort and self.barReversalShort > 0.02:
            self.MarketOrder(self.ccypair, self.CloseShortPosition)
            self.Liquidate(self.ccypair)

    def OnOrderEvent(self, orderEvent):
        if orderEvent.Status == OrderStatus.Filled:
            self.lastOrderEvent = orderEvent
            self.Debug("Time: {}, Order ID: {}, Order Event: {}".format(self.Time, str(self.lastOrderEvent.OrderId), orderEvent))