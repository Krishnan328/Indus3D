import os
import requests
import logging

SPOOLMAN_URL = os.getenv("SPOOLMAN_URL", "")

def get_active_spool():
    """Fetch the active spool for this printer. For now, just returns the first spool or None."""
    if not SPOOLMAN_URL:
        return None
    try:
        # Get all spools
        res = requests.get(f"{SPOOLMAN_URL}/api/v1/spool", timeout=2)
        if res.ok:
            spools = res.json()
            if spools:
                return spools[0] # Simplification: Just grab the first spool
    except Exception as e:
        logging.info(f"⚠️ Spoolman fetch failed: {e}")
    return None

def get_spool_price_per_g():
    spool = get_active_spool()
    if not spool:
        return 0.0
    
    # Spoolman returns price and weight
    price = spool.get("price", 0.0)
    weight = spool.get("weight", 1000.0) # default to 1kg
    if weight > 0:
        return price / weight
    return 0.0
