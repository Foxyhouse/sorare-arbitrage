import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- CONFIGURATION ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

def get_segmented_floors(player_slug, season_name, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetSegFloors($slug: String!) {
      tokens {
        all_offers: liveSingleSaleOffers(playerSlug: $slug, first: 40) {
          nodes { 
            senderSide { anyCards { rarityTyped season { name } } }
            receiverSide { amounts { eurCents } } 
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers, timeout=10).json()
        nodes = res.get('data', {}).get('tokens', {}).get('all_offers', {}).get('nodes', [])
        lim_prices, rare_prices = [], []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            card = cards[0]
            if card['season']['name'] == season_name:
                eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if eur:
                    p = float(eur) / 100
                    if card['rarityTyped'] == 'limited': lim_prices.append(p)
                    if card['rarityTyped'] == 'rare': rare_prices.append(p)
        return min(lim_prices) if lim_prices else None, min(rare_prices) if rare_prices else None
    except: return None, None

def scan_arbitrage_debug(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    
    # On enlève 'updatedAfter' qui semble causer le retour vide
    query = """
    query GetFluxDebug {
      tokens {
        liveSingleSaleOffers(first: 100, sport: FOOTBALL) {
          nodes {
            senderSide { 
              anyCards { rarityTyped season { name } anyPlayer { displayName slug } } 
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        response = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15)
        res_json = response.json()
        
        # DEBUG : On affiche le JSON brut si c'est vide
        if "errors" in res_json:
            return [], f"Erreur API : {res_json['errors'][0]['message']}"
            
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        if not nodes:
            return [], "L'API renvoie 0 nodes (liste vide)."

        current_season = "2025-2026"
        findings = []
        
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            
            if eur_cents and cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                card = cards[0]
                s_name = card.get('season', {}).get('name', "Inconnue")
                p_slug = card['anyPlayer']['slug']
                
                f_lim, f_rare = get_segmented_floors(p_slug, s_name, jwt_token)
                price_now = float(eur_cents) / 100
                ratio = round(price_now / f_lim, 2) if f_lim else None
                
                findings.append({
                    "Vente": n.get('startDate'),
                    "Joueur": card['anyPlayer']['displayName'],
                    "Saison": s_name,
                    "Type": "🟢 In-Season" if current_season in s_name else "Classic",
                    "Prix (€)": price_now,
                    "Floor Rare (€)": f_rare,
                    "Floor Lim (€)": f_lim,
                    "Ratio": ratio,
                    "Slug": p_slug
                })
        
        # Tri manuel par date
        findings = sorted(findings, key=lambda x: x['Vente'], reverse=True)
        return findings, None
    except Exception as e:
        return [], f"Crash : {str(e)}"

# --- UI ---
st.title("🔎 Debug Scanner Arbitrage")

if st.session_state.get('token'):
    if st.button("🚀 Lancer l'analyse forcée"):
        results, err = scan_arbitrage_debug(st.session_state['token'])
        
        if err:
            st.error(err)
        elif results:
            st.success(f"{len(results)} Rares trouvées.")
            df = pd.DataFrame(results).drop(columns=['Slug'])
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("Aucune carte Rare identifiée dans les 100 dernières annonces.")
