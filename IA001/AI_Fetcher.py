import requests
import json
from datetime import datetime, timezone
import re
import os
import time
import logging

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = "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"

PAIRS = [
    "BTC/USDT", "BCH/USDT", "ETH/USDT", "LINK/USDT", "LTC/USDT", "SOL/USDT",
    "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOT/USDT", "ETC/USDT", "ALGO/USDT", "LUNA/USDT"
]

PROMPT_TEMPLATE = '''You are an expert cryptocurrency trading AI. Analyze real-time market conditions for the following trading pairs as of the current timestamp. For each pair, return:
1. Trading decision: 'buy', 'sell', or 'hold'
2. If 'buy': recommended allocation percentage (0-100) of available capital
3. If 'sell': recommended percentage (0-100) of current holdings to sell
4. For 'hold': both percentages = 0
5. Additionally, recommend the exact amount of each crypto to buy (in units), given the user's current money and current holdings.
6. Be safe and maximize profit, using risk-adjusted position sizing.

Output must be valid JSON only, i repeat in a SINGLE JSON format file with this exact structure:
[
  {{"pair":"BTC/USDT","decision":"...","buy_percentage":0,"sell_percentage":0,"buy_amount":0}},
  ...
]

Pairs to analyze:
BTC/USDT, BCH/USDT, ETH/USDT, LINK/USDT, LTC/USDT, SOL/USDT, BNB/USDT, XRP/USDT, ADA/USDT, DOT/USDT, ETC/USDT, ALGO/USDT, LUNA/USDT

Use these analysis parameters:
- Consider technical indicators (RSI, MACD, moving averages)
- Evaluate volume trends and support/resistance levels
- Incorporate relevant market news sentiment
- Apply risk-adjusted position sizing
- Current timestamp UTC + 0: {timestamp}
- User's current available money: {current_money} USDT
- User's current crypto holdings: {current_holdings}

Here is recent OHLCV data for each pair (last 24 entries), remember to use the indicator to make the best decision:
{all_ohlcv}

Analyze carefully and make sure to use all the data to make the best decision, make your result in a single JSON file.
'''

def check_rate_limit():
    """Vérifie et applique un délai pour respecter les limites de l'API"""
    rate_limit_file = "api_rate_limit.json"
    current_time = time.time()
    min_interval = 300  # Minimum 5 minutes (300 secondes) entre les appels API
    
    # Charger le dernier appel API
    last_call_time = 0
    if os.path.exists(rate_limit_file):
        try:
            with open(rate_limit_file, 'r') as f:
                data = json.load(f)
                last_call_time = data.get('last_call', 0)
        except:
            pass
    
    # Calculer le délai nécessaire
    time_since_last_call = current_time - last_call_time
    if time_since_last_call < min_interval:
        wait_time = min_interval - time_since_last_call
        logger.info(f"Rate limit: attente de {wait_time:.1f} secondes...")
        return False  # Retourner False si on doit attendre
    
    # Sauvegarder le timestamp du nouvel appel
    with open(rate_limit_file, 'w') as f:
        json.dump({'last_call': time.time()}, f)
    
    return True

def try_parse_json(content_stripped):
    # Try direct parse
    try:
        return json.loads(content_stripped)
    except Exception:
        pass
    # Try to extract the first valid JSON array from the string
    array_match = re.search(r'(\[\s*{[\s\S]+?\}\s*\])', content_stripped)
    if array_match:
        try:
            return json.loads(array_match.group(1))
        except Exception:
            pass
    # Try to remove trailing commas before closing brackets
    fixed = re.sub(r',\s*([}\]])', r'\1', content_stripped)
    try:
        return json.loads(fixed)
    except Exception:
        pass
    return None

def load_fallback_analysis():
    """Charge une analyse de fallback basée sur les indicateurs simples des données crypto"""
    fallback_analysis = []
    
    for pair in PAIRS:
        symbol = pair.replace('/', '').upper()
        filename = f"{symbol}.json"
        
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
                
                logger.info(f"Fallback {pair}: {decision} ({percent_change_24h:.2f}%)")
                
            except Exception as e:
                logger.error(f"Erreur lors du chargement de {filename}: {e}")
        
        fallback_analysis.append({
            "pair": pair,
            "decision": decision,
            "buy_percentage": buy_percentage,
            "sell_percentage": sell_percentage,
            "buy_amount": buy_amount
        })
    
    return fallback_analysis

def analyze_crypto_pairs(current_money, current_holdings, **kwargs):
    analysis_file = "crypto_analysis.json"
    
    # Vérifier si une analyse récente existe déjà (moins de 5 minutes)
    if os.path.exists(analysis_file):
        try:
            file_age = time.time() - os.path.getmtime(analysis_file)
            if file_age < 300:  # 5 minutes
                logger.info(f"Utilisation de l'analyse existante (âge: {file_age:.0f}s)")
                with open(analysis_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                return existing_data.get('result', [])
        except Exception as e:
            logger.warning(f"Impossible de lire l'analyse existante: {e}")
    
    # Vérifier la limite de taux avant l'appel API
    if not check_rate_limit():
        logger.info("Rate limit atteint, utilisation de l'analyse de fallback")
        result_data = load_fallback_analysis()
        
        # Sauvegarder le fallback
        output = {
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "result": result_data,
            "fallback": True,
            "reason": "rate_limit"
        }
        
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Analyse de fallback sauvegardée: {len(result_data)} paires")
        return result_data
    
    try:
        # Load OHLCV data for all pairs
        all_ohlcv = {}
        for pair in PAIRS:
            symbol = pair.replace('/', '').upper()
            filename = f"{symbol}.json"
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # If the data is a dict with 'ohlcv', extract the list
                if isinstance(data, dict) and 'ohlcv' in data:
                    ohlcv = data['ohlcv']
                else:
                    ohlcv = data
                all_ohlcv[pair] = ohlcv[-24:]  # last 24 entries
            else:
                all_ohlcv[pair] = []
        
        # Get current UTC timestamp (timezone-aware)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Build the prompt
        prompt = PROMPT_TEMPLATE.format(
            timestamp=timestamp,
            current_money=current_money,
            current_holdings=json.dumps(current_holdings, ensure_ascii=False),
            all_ohlcv=json.dumps(all_ohlcv, ensure_ascii=False)
        )
        
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek/deepseek-chat-v3-0324:free",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        logger.info("Envoi de la requête à l'API DeepSeek...")
        response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        
        if response.status_code == 429:
            logger.warning("Rate limit atteint, utilisation de l'analyse de fallback")
            result_data = load_fallback_analysis()
        else:
            response.raise_for_status()
            result = response.json()
            
            # Extract the assistant's message content (the JSON answer)
            content = result["choices"][0]["message"]["content"]
            
            # If the content is surrounded by triple backticks, extract the inner JSON
            content_stripped = content.strip()
            match = re.match(r"^```(?:json)?\s*([\s\S]+?)\s*```$", content_stripped)
            if match:
                content_stripped = match.group(1).strip()
            
            # Try to parse the content as JSON robustly
            answer_json = try_parse_json(content_stripped)
            
            if answer_json is not None:
                result_data = answer_json
                logger.info("Analyse DeepSeek réussie")
            else:
                logger.warning("Impossible de parser la réponse DeepSeek, utilisation du fallback")
                # Sauvegarder la réponse brute pour debug
                with open("crypto_analysis_raw.txt", "w", encoding="utf-8") as f:
                    f.write(content)
                result_data = load_fallback_analysis()
        
        # Sauvegarder le résultat final - TOUJOURS créer le fichier
        output = {
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "result": result_data
        }
        
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Analyse sauvegardée: {len(result_data)} paires analysées")
        return result_data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API: {e}")
        logger.info("Utilisation de l'analyse de fallback")
        result_data = load_fallback_analysis()
        
        # Sauvegarder le fallback - TOUJOURS créer le fichier
        output = {
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "result": result_data,
            "fallback": True,
            "error": str(e)
        }
        
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Analyse de fallback sauvegardée: {len(result_data)} paires")
        return result_data
    
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
        # En cas d'erreur, créer quand même le fichier avec le fallback
        result_data = load_fallback_analysis()
        
        output = {
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "result": result_data,
            "fallback": True,
            "error": str(e)
        }
        
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Analyse de fallback d'urgence sauvegardée: {len(result_data)} paires")
        return result_data

if __name__ == "__main__":
    # Example usage:
    # User has 100 USDT and no crypto holdings
    current_money = 100.0
    current_holdings = {}
    analyze_crypto_pairs(current_money, current_holdings)