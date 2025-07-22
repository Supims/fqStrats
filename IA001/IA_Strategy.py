# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these libs ---
import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime, timezone
import talib.abstract as ta
from freqtrade.strategy import IStrategy
from typing import Dict, List, Optional, Tuple, Union
import subprocess
import json
import os
import time
import logging

class IA_Strategy(IStrategy):
    """
    Stratégie FreqTrade basée uniquement sur les décisions de l'IA DeepSeek
    """
    
    # Métadonnées de la stratégie
    INTERFACE_VERSION = 3
    
    # Paramètres de la stratégie
    timeframe = '5m'
    can_short = False
    
    # Configuration des ordres
    order_types = {
        'entry': 'market',
        'exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }
    
    # Paramètres de risque - Laisser l'IA décider
    stoploss = -0.99  # Stop loss très large pour laisser l'IA gérer
    
    # Configuration du ROI - Laisser l'IA décider
    minimal_roi = {
        "0": 10.0  # ROI très élevé pour laisser l'IA décider quand sortir
    }
    
    # Variables de classe pour gérer l'analyse IA - AUGMENTATION DES INTERVALLES
    _last_analysis_time = None
    _analysis_cache = None
    _analysis_interval = 300  # 5 minutes entre analyses IA
    _data_fetch_interval = 300  # 5 minutes entre récupérations de données
    _last_data_fetch_time = None
    _analysis_in_progress = False  # Flag pour éviter les analyses simultanées
    
    # Logging
    logger = logging.getLogger(__name__)
    
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Pas d'indicateurs techniques - on se base uniquement sur l'IA
        """
        # On ajoute juste une colonne pour éviter les erreurs
        dataframe['ai_signal'] = 0
        return dataframe
    
    def run_data_fetcher(self) -> bool:
        """
        Lance le script Get_Crypto_Data.py pour récupérer les données (avec gestion de fréquence)
        """
        current_time = time.time()
        
        # Vérifier si on doit récupérer de nouvelles données
        if (self._last_data_fetch_time is not None and 
            current_time - self._last_data_fetch_time < self._data_fetch_interval):
            time_remaining = int(self._data_fetch_interval - (current_time - self._last_data_fetch_time))
            self.logger.debug(f"Données récentes disponibles, prochaine récupération dans {time_remaining} secondes")
            return True  # Considérer comme succès si données récentes
        
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(script_dir, 'Get_Crypto_Data.py')
            
            if not os.path.exists(script_path):
                self.logger.error(f"Script Get_Crypto_Data.py non trouvé: {script_path}")
                return False
            
            self.logger.info("Lancement du script Get_Crypto_Data.py...")
            result = subprocess.run(
                ['python', script_path], 
                capture_output=True, 
                text=True, 
                timeout=120,
                cwd=script_dir
            )
            
            if result.returncode == 0:
                self.logger.info("Données crypto récupérées avec succès")
                self._last_data_fetch_time = current_time
                # Attendre un peu pour s'assurer que les fichiers sont bien écrits
                time.sleep(2)
                return True
            else:
                self.logger.error(f"Erreur lors de la récupération des données: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout lors de la récupération des données")
            return False
        except Exception as e:
            self.logger.error(f"Erreur inattendue lors de la récupération des données: {e}")
            return False
    
    def get_freqtrade_balance_and_holdings(self):
        """
        Récupère le solde et les holdings directement depuis FreqTrade
        """
        try:
            # Récupérer le solde disponible depuis FreqTrade
            if hasattr(self.dp, 'wallet') and self.dp.wallet:
                wallet = self.dp.wallet
                # Solde disponible en devise de base (USDT)
                stake_currency = self.config.get('stake_currency', 'USDT')
                current_balance = wallet.get_free(stake_currency)
                
                # Holdings actuels
                current_holdings = {}
                for currency in wallet.get_all_balances():
                    if currency != stake_currency and wallet.get_total(currency) > 0:
                        # Convertir le nom de la crypto pour correspondre aux paires
                        current_holdings[currency] = wallet.get_total(currency)
                
                self.logger.info(f"Balance FreqTrade: {current_balance} {stake_currency}")
                self.logger.info(f"Holdings FreqTrade: {current_holdings}")
                
                return current_balance, current_holdings
            else:
                # Fallback si pas d'accès au wallet
                self.logger.warning("Impossible d'accéder au wallet FreqTrade, utilisation de valeurs par défaut")
                return 1000.0, {}
                
        except Exception as e:
            self.logger.error(f"Erreur lors de la récupération du wallet FreqTrade: {e}")
            return 1000.0, {}
    
    def create_fallback_analysis(self) -> List[Dict]:
        """
        Crée une analyse de fallback basée sur les données disponibles
        """
        fallback_analysis = []
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        pairs = [
            "BTC/USDT", "BCH/USDT", "ETH/USDT", "LINK/USDT", "LTC/USDT", "SOL/USDT",
            "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOT/USDT", "ETC/USDT", "ALGO/USDT", "LUNA/USDT"
        ]
        
        for pair in pairs:
            symbol = pair.replace('/', '').upper()
            filename = os.path.join(script_dir, f"{symbol}.json")
            
            decision = "hold"
            buy_percentage = 0
            sell_percentage = 0
            buy_amount = 0
            
            if os.path.exists(filename):
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Utiliser l'indicateur simple du fichier
                    indicator = data.get('indicator', 'hold')
                    percent_change_24h = data.get('percent_change_24h', 0)
                    
                    if indicator == 'buy' and percent_change_24h > 2:
                        decision = 'buy'
                        buy_percentage = min(15, max(5, abs(percent_change_24h) * 2))  # Entre 5% et 15%
                    elif indicator == 'sell' and percent_change_24h < -2:
                        decision = 'sell'
                        sell_percentage = min(50, max(10, abs(percent_change_24h) * 3))  # Entre 10% et 50%
                    
                    self.logger.debug(f"Fallback {pair}: {decision} ({percent_change_24h:.2f}%)")
                    
                except Exception as e:
                    self.logger.error(f"Erreur lors du chargement de {filename}: {e}")
            
            fallback_analysis.append({
                "pair": pair,
                "decision": decision,
                "buy_percentage": buy_percentage,
                "sell_percentage": sell_percentage,
                "buy_amount": buy_amount
            })
        
        return fallback_analysis
    
    def run_ai_analysis(self) -> Optional[List[Dict]]:
        """
        Lance le script AI_Fetcher.py pour obtenir l'analyse IA avec fallback amélioré
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        analysis_file = os.path.join(script_dir, 'crypto_analysis.json')
        
        try:
            ai_script_path = os.path.join(script_dir, 'AI_Fetcher.py')
            
            if not os.path.exists(ai_script_path):
                self.logger.error(f"Script AI_Fetcher.py non trouvé: {ai_script_path}")
                return self.create_fallback_analysis()
            
            self.logger.info("Tentative d'analyse IA avec DeepSeek...")
            
            # Récupérer les vraies données FreqTrade
            current_balance, current_holdings = self.get_freqtrade_balance_and_holdings()
            
            # Supprimer l'ancien fichier d'analyse s'il existe
            if os.path.exists(analysis_file):
                try:
                    os.remove(analysis_file)
                except:
                    pass
            
            # Modification temporaire du script AI_Fetcher pour passer les paramètres
            temp_script_path = os.path.join(script_dir, 'temp_ai_analysis.py')
            
            script_content = f"""
import sys
import os
sys.path.append(r'{script_dir}')
os.chdir(r'{script_dir}')

try:
    from AI_Fetcher import analyze_crypto_pairs
    import json

    current_money = {current_balance}
    current_holdings = {json.dumps(current_holdings)}

    print(f"Analyse IA - Balance: {{current_money}}, Holdings: {{current_holdings}}")
    
    result = analyze_crypto_pairs(current_money, current_holdings)
    
    # Vérifier si le fichier a été créé
    analysis_file = "crypto_analysis.json"
    if os.path.exists(analysis_file):
        print(f"SUCCESS: Fichier d'analyse créé")
    else:
        print(f"WARNING: Fichier d'analyse non créé - probablement fallback utilisé")
    
    print("Analyse terminée")
    
except Exception as e:
    print(f"ERREUR: {{e}}")
    import traceback
    traceback.print_exc()
"""
            
            # Créer et exécuter le script temporaire
            with open(temp_script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            result = subprocess.run(
                ['python', temp_script_path], 
                capture_output=True, 
                text=True, 
                timeout=300,
                cwd=script_dir
            )
            
            # Nettoyer le fichier temporaire
            try:
                if os.path.exists(temp_script_path):
                    os.remove(temp_script_path)
            except:
                pass
            
            # Attendre le fichier d'analyse
            max_wait = 10
            for wait_time in range(max_wait):
                time.sleep(1)
                if os.path.exists(analysis_file):
                    break
            
            # Lire le résultat
            if os.path.exists(analysis_file):
                try:
                    with open(analysis_file, 'r', encoding='utf-8') as f:
                        analysis_data = json.load(f)
                    
                    result_data = analysis_data.get('result', [])
                    if result_data:
                        self.logger.info(f"Analyse IA réussie - {len(result_data)} paires analysées")
                        return result_data
                    else:
                        self.logger.warning("Fichier d'analyse vide, utilisation du fallback")
                        return self.create_fallback_analysis()
                        
                except json.JSONDecodeError as e:
                    self.logger.error(f"Erreur de parsing JSON: {e}")
                    return self.create_fallback_analysis()
            else:
                self.logger.warning("Pas de fichier d'analyse créé, utilisation du fallback")
                return self.create_fallback_analysis()
                
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout lors de l'analyse IA, utilisation du fallback")
            return self.create_fallback_analysis()
        except Exception as e:
            self.logger.error(f"Erreur lors de l'analyse IA: {e}, utilisation du fallback")
            return self.create_fallback_analysis()
    
    def get_ai_analysis(self) -> List[Dict]:
        """
        Récupère l'analyse IA (avec cache pour éviter les appels trop fréquents)
        """
        current_time = time.time()
        
        # Éviter les analyses simultanées
        if self._analysis_in_progress:
            self.logger.debug("Analyse IA déjà en cours, utilisation du cache")
            return self._analysis_cache or self.create_fallback_analysis()
        
        # Vérifier si une nouvelle analyse est nécessaire
        if (self._last_analysis_time is None or 
            current_time - self._last_analysis_time > self._analysis_interval):
            
            self._analysis_in_progress = True
            try:
                time_since_last = int(current_time - (self._last_analysis_time or 0))
                self.logger.info(f"Nouvelle analyse IA requise (dernière il y a {time_since_last}s)")
                
                # Récupérer les données crypto (avec gestion de fréquence)
                data_success = self.run_data_fetcher()
                
                if data_success:
                    # Attendre un peu entre la récupération des données et l'analyse
                    time.sleep(2)
                    
                    # Lancer l'analyse IA
                    analysis_result = self.run_ai_analysis()
                    
                    if analysis_result and len(analysis_result) > 0:
                        self._analysis_cache = analysis_result
                        self._last_analysis_time = current_time
                        self.logger.info(f"Analyse IA mise à jour: {len(analysis_result)} paires")
                    else:
                        self.logger.warning("Analyse IA échouée, conservation du cache")
                else:
                    self.logger.warning("Récupération des données échouée, conservation du cache")
            
            finally:
                self._analysis_in_progress = False
        else:
            time_remaining = int(self._analysis_interval - (current_time - self._last_analysis_time))
            self.logger.debug(f"Utilisation du cache IA (prochaine dans {time_remaining}s)")
        
        # Retourner le cache ou créer un fallback
        return self._analysis_cache or self.create_fallback_analysis()
    
    def get_ai_decision_for_pair(self, pair: str, analysis_data: List[Dict]) -> Dict:
        """
        Récupère la décision IA pour une paire spécifique
        """
        if not analysis_data:
            self.logger.debug(f"Pas de données d'analyse pour {pair}")
            return {"decision": "hold", "buy_percentage": 0, "sell_percentage": 0}
        
        # Rechercher la paire exacte
        for item in analysis_data:
            if item.get("pair") == pair:
                decision = item.get("decision", "hold")
                buy_pct = item.get("buy_percentage", 0)
                sell_pct = item.get("sell_percentage", 0)
                
                if decision != "hold" or buy_pct > 0 or sell_pct > 0:
                    self.logger.info(f"IA {pair}: {decision} - Buy: {buy_pct}% - Sell: {sell_pct}%")
                
                return {
                    "decision": decision,
                    "buy_percentage": buy_pct,
                    "sell_percentage": sell_pct,
                    "buy_amount": item.get("buy_amount", 0)
                }
        
        # Si pas trouvé, retourner hold
        return {"decision": "hold", "buy_percentage": 0, "sell_percentage": 0}
    
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Signal d'entrée basé uniquement sur la décision IA
        """
        # Initialiser par défaut
        dataframe.loc[:, 'enter_long'] = 0
        
        # Récupérer l'analyse IA (une seule fois par appel)
        analysis_data = self.get_ai_analysis()
        ai_decision = self.get_ai_decision_for_pair(metadata['pair'], analysis_data)
        
        # Signal d'achat uniquement basé sur l'IA
        if ai_decision.get("decision") == "buy" and ai_decision.get("buy_percentage", 0) > 0:
            # Signal sur les dernières bougies pour s'assurer qu'il soit pris en compte
            dataframe.loc[dataframe.index[-3:], 'enter_long'] = 1
            self.logger.info(f"Signal BUY pour {metadata['pair']} (confiance: {ai_decision.get('buy_percentage')}%)")
        
        return dataframe
    
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Signal de sortie basé uniquement sur la décision IA
        """
        # Initialiser par défaut
        dataframe.loc[:, 'exit_long'] = 0
        
        # Récupérer l'analyse IA (réutiliser le cache si récent)
        analysis_data = self.get_ai_analysis()
        ai_decision = self.get_ai_decision_for_pair(metadata['pair'], analysis_data)
        
        # Signal de vente uniquement basé sur l'IA
        if ai_decision.get("decision") == "sell" and ai_decision.get("sell_percentage", 0) > 0:
            # Signal sur les dernières bougies
            dataframe.loc[dataframe.index[-3:], 'exit_long'] = 1
            self.logger.info(f"Signal SELL pour {metadata['pair']} (confiance: {ai_decision.get('sell_percentage')}%)")
        
        return dataframe
    
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                          proposed_stake: float, min_stake: Optional[float], max_stake: float,
                          leverage: float, entry_tag: Optional[str], side: str,
                          **kwargs) -> float:
        """
        Calcule le montant à investir basé sur les recommandations IA
        """
        try:
            # Récupérer l'analyse IA
            analysis_data = self.get_ai_analysis()
            ai_decision = self.get_ai_decision_for_pair(pair, analysis_data)
            
            # Utiliser le pourcentage recommandé par l'IA
            buy_percentage = ai_decision.get("buy_percentage", 0) / 100.0
            
            if buy_percentage > 0:
                # Récupérer le solde réel
                current_balance, _ = self.get_freqtrade_balance_and_holdings()
                
                # Calculer le montant basé sur le pourcentage IA et le solde réel
                ai_stake = current_balance * buy_percentage
                
                # S'assurer que c'est dans les limites FreqTrade
                if min_stake:
                    ai_stake = max(ai_stake, min_stake)
                ai_stake = min(ai_stake, max_stake)
                
                self.logger.info(f"Stake IA pour {pair}: {buy_percentage*100:.1f}% = {ai_stake:.2f}")
                return ai_stake
            else:
                # Pas de recommandation d'achat, utiliser le minimum
                return min_stake or proposed_stake
                
        except Exception as e:
            self.logger.error(f"Erreur dans custom_stake_amount: {e}")
            return proposed_stake
    
    def custom_exit(self, pair: str, trade: 'Trade', current_time: datetime, 
                   current_rate: float, current_profit: float, **kwargs) -> Optional[Union[str, bool]]:
        """
        Logique de sortie personnalisée basée uniquement sur l'IA
        """
        try:
            # Récupérer l'analyse IA
            analysis_data = self.get_ai_analysis()
            ai_decision = self.get_ai_decision_for_pair(pair, analysis_data)
            
            # Vérifier si l'IA recommande une vente
            if ai_decision.get("decision") == "sell":
                sell_confidence = ai_decision.get("sell_percentage", 0)
                
                if sell_confidence > 0:
                    self.logger.info(f"EXIT IA {pair} ({sell_confidence}%) - Profit: {current_profit*100:.2f}%")
                    return f"ai_sell_{sell_confidence}"
            
            # Pas de signal de sortie IA
            return None
            
        except Exception as e:
            self.logger.error(f"Erreur dans custom_exit: {e}")
            return None
    
    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                          time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                          side: str, **kwargs) -> bool:
        """
        Confirmation finale avant d'entrer en trade
        """
        try:
            # Dernière vérification avec l'IA
            analysis_data = self.get_ai_analysis()
            ai_decision = self.get_ai_decision_for_pair(pair, analysis_data)
            
            if ai_decision.get("decision") == "buy" and ai_decision.get("buy_percentage", 0) > 0:
                confidence = ai_decision.get("buy_percentage", 0)
                self.logger.info(f"CONFIRME ACHAT {pair} (IA: {confidence}%) - Amount: {amount:.6f}")
                return True
            else:
                self.logger.info(f"REJETE ACHAT {pair} (IA: {ai_decision.get('decision')})")
                return False
                
        except Exception as e:
            self.logger.error(f"Erreur dans confirm_trade_entry: {e}")
            return False
    
    def confirm_trade_exit(self, pair: str, trade: 'Trade', order_type: str, amount: float,
                         rate: float, time_in_force: str, exit_reason: str,
                         current_time: datetime, **kwargs) -> bool:
        """
        Confirmation finale avant de sortir d'un trade
        """
        try:
            # Si c'est un signal IA, toujours confirmer
            if exit_reason.startswith('ai_sell'):
                self.logger.info(f"CONFIRME VENTE IA {pair} - Raison: {exit_reason}")
                return True
            
            # Pour ROI, vérifier avec l'IA
            if exit_reason == "roi":
                analysis_data = self.get_ai_analysis()
                ai_decision = self.get_ai_decision_for_pair(pair, analysis_data)
                
                # Si l'IA dit encore d'acheter, peut-être refuser la sortie ROI
                if ai_decision.get("decision") == "buy":
                    self.logger.info(f"ROI mais IA dit BUY {pair}, maintien position")
                    return False
            
            return True
                
        except Exception as e:
            self.logger.error(f"Erreur dans confirm_trade_exit: {e}")
            return True