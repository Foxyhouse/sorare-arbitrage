def scan_arbitrage_final(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # On définit une date très proche (ex: les dernières 24h) pour filtrer les vieux stocks
    from datetime import datetime, timedelta
    recent_limit = (datetime.now() - timedelta(hours=24)).isoformat() + "Z"

    query = """
    query GetFlux($since: ISO8601DateTime) {
      tokens {
        liveSingleSaleOffers(first: 100, sport: FOOTBALL, updatedAfter: $since) {
          nodes {
            senderSide {
              anyCards {
                slug
                rarityTyped
                anyPlayer { displayName slug }
              }
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        # On passe la variable 'since' pour nettoyer le flux
        response = requests.post(API_URL, json={'query': query, 'variables': {'since': recent_limit}}, headers=headers)
        res_json = response.json()
        st.session_state['audit_raw'] = res_json
        
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        findings = []
        for n in nodes:
            # On ignore les offres sans prix en euros (échanges)
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            if eur_cents is None: continue

            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            c = cards[0]
            if str(c.get('rarityTyped')).lower() == 'rare':
                findings.append({
                    "Date": n.get('startDate'),
                    "Joueur": c.get('anyPlayer', {}).get('displayName'),
                    "Slug": c.get('anyPlayer', {}).get('slug'),
                    "Prix Rare (€)": float(eur_cents) / 100
                })
        
        # Tri manuel par date pour être sûr d'avoir le plus récent en haut
        findings = sorted(findings, key=lambda x: x['Date'], reverse=True)

        for item in findings[:15]: 
            item['Floor Limited (€)'] = get_limited_floor(item['Slug'], jwt_token)
            if item['Floor Limited (€)']:
                item['Ratio'] = round(item['Prix Rare (€)'] / item['Floor Limited (€)'], 2)
            else:
                item['Ratio'] = "N/A"
                
        return findings
    except Exception as e:
        return []
