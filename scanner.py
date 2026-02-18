#!/usr/bin/env python3
"""
Pump.fun Token Scanner - Analyzes recent token launches for investment opportunities
Uses Helius API to fetch and score tokens based on holder count, age, dev holdings, and liquidity
"""

import httpx
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
import time

# Configuration
HELIUS_API_KEY = "a2645403-e2f9-4bc9-806c-927051e0718a"
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
BASE_URL = "https://api.helius.xyz/v0"
RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# Scoring weights
WEIGHTS = {
    "holders": 0.35,
    "age": 0.25,
    "dev_holdings": 0.25,
    "liquidity": 0.15
}

# Thresholds
THRESHOLDS = {
    "excellent_holders": 1000,
    "good_holders": 500,
    "min_holders": 100,
    "sweet_spot_age_min": 24,
    "sweet_spot_age_max": 72,
    "dev_red_flag": 50,
    "dev_warning": 30,
    "great_liquidity": 50000,
    "good_liquidity": 10000,
    "min_liquidity": 1000
}


def fetch_recent_transactions(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch recent transactions from pump.fun program using parsed transactions"""
    url = f"{BASE_URL}/addresses/{PUMP_FUN_PROGRAM}/transactions"
    params = {
        "api-key": HELIUS_API_KEY
    }
    
    print(f"Fetching recent transactions from pump.fun program...")
    
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            print(f"Retrieved {len(data) if isinstance(data, list) else 0} transactions")
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []


def search_assets_by_creator(creator: str = PUMP_FUN_PROGRAM, limit: int = 50) -> List[str]:
    """Search for assets created by pump.fun program using DAS API"""
    url = f"{BASE_URL}/assets"
    params = {"api-key": HELIUS_API_KEY}
    
    payload = {
        "creatorAddress": creator,
        "limit": limit,
        "page": 1
    }
    
    print(f"Searching for pump.fun assets using DAS API...")
    
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, params=params, json=payload)
            response.raise_for_status()
            data = response.json()
            
            items = data.get("items", [])
            mints = [item.get("id") for item in items if item.get("id")]
            
            print(f"Found {len(mints)} assets from pump.fun")
            return mints
    except Exception as e:
        print(f"Error searching assets: {e}")
        return []


def extract_token_mints(transactions: List[Dict[str, Any]]) -> List[str]:
    """Extract unique token mint addresses from transactions"""
    mints = set()
    
    for tx in transactions:
        # Look for token balances changes indicating new token creation
        if "tokenTransfers" in tx:
            for transfer in tx.get("tokenTransfers", []):
                if "mint" in transfer:
                    mints.add(transfer["mint"])
        
        # Also check native transfers
        if "nativeTransfers" in tx:
            for transfer in tx.get("nativeTransfers", []):
                if "mint" in transfer:
                    mints.add(transfer["mint"])
                    
        # Check accountData for mints
        if "accountData" in tx:
            for account in tx.get("accountData", []):
                if isinstance(account, dict) and "mint" in account:
                    mints.add(account["mint"])
    
    mints_list = list(mints)
    print(f"Found {len(mints_list)} unique token mints")
    return mints_list


def fetch_token_metadata_batch(mints: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch metadata for multiple tokens"""
    if not mints:
        return {}
        
    url = f"{BASE_URL}/token-metadata"
    params = {"api-key": HELIUS_API_KEY}
    
    print(f"Fetching metadata for {len(mints)} tokens...")
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, params=params, json={"mintAccounts": mints})
            response.raise_for_status()
            data = response.json()
            
            # Map by mint address
            metadata_map = {}
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "account" in item:
                        metadata_map[item["account"]] = item
            
            print(f"Retrieved metadata for {len(metadata_map)} tokens")
            return metadata_map
    except Exception as e:
        print(f"Error fetching metadata: {e}")
        return {}


def get_token_supply(mint: str) -> Optional[Dict[str, Any]]:
    """Get token supply using RPC"""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                RPC_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenSupply",
                    "params": [mint]
                }
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("result")
            if result:
                return result.get("value", {})
            return {}
    except Exception as e:
        return {}


def get_token_largest_accounts(mint: str) -> List[Dict[str, Any]]:
    """Get largest token holders using RPC"""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                RPC_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenLargestAccounts",
                    "params": [mint]
                }
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("result")
            if result and isinstance(result, dict):
                return result.get("value", [])
            return []
    except Exception as e:
        return []


def calculate_holder_score(holder_count: int) -> float:
    """Score based on holder count (0-100)"""
    if holder_count >= THRESHOLDS["excellent_holders"]:
        return 100.0
    elif holder_count >= THRESHOLDS["good_holders"]:
        return 70.0 + (holder_count - THRESHOLDS["good_holders"]) / (THRESHOLDS["excellent_holders"] - THRESHOLDS["good_holders"]) * 30.0
    elif holder_count >= THRESHOLDS["min_holders"]:
        return 40.0 + (holder_count - THRESHOLDS["min_holders"]) / (THRESHOLDS["good_holders"] - THRESHOLDS["min_holders"]) * 30.0
    else:
        return (holder_count / THRESHOLDS["min_holders"]) * 40.0


def calculate_age_score(age_hours: float) -> float:
    """Score based on token age (0-100), sweet spot is 24-72 hours"""
    if THRESHOLDS["sweet_spot_age_min"] <= age_hours <= THRESHOLDS["sweet_spot_age_max"]:
        return 100.0
    elif age_hours < THRESHOLDS["sweet_spot_age_min"]:
        return (age_hours / THRESHOLDS["sweet_spot_age_min"]) * 100.0
    else:
        excess = age_hours - THRESHOLDS["sweet_spot_age_max"]
        decay = max(0, 100.0 - (excess / 24) * 20)
        return decay


def calculate_dev_holdings_score(dev_percentage: float) -> float:
    """Score based on dev holdings (0-100), lower is better"""
    if dev_percentage >= THRESHOLDS["dev_red_flag"]:
        return 0.0
    elif dev_percentage >= THRESHOLDS["dev_warning"]:
        return 50.0 - ((dev_percentage - THRESHOLDS["dev_warning"]) / (THRESHOLDS["dev_red_flag"] - THRESHOLDS["dev_warning"])) * 50.0
    else:
        return 100.0 - (dev_percentage / THRESHOLDS["dev_warning"]) * 50.0


def calculate_liquidity_score(liquidity: float) -> float:
    """Score based on liquidity (0-100)"""
    if liquidity >= THRESHOLDS["great_liquidity"]:
        return 100.0
    elif liquidity >= THRESHOLDS["good_liquidity"]:
        return 70.0 + (liquidity - THRESHOLDS["good_liquidity"]) / (THRESHOLDS["great_liquidity"] - THRESHOLDS["good_liquidity"]) * 30.0
    elif liquidity >= THRESHOLDS["min_liquidity"]:
        return 40.0 + (liquidity - THRESHOLDS["min_liquidity"]) / (THRESHOLDS["good_liquidity"] - THRESHOLDS["min_liquidity"]) * 30.0
    else:
        return (liquidity / THRESHOLDS["min_liquidity"]) * 40.0


def analyze_token(mint: str, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Analyze a single token and return scored data"""
    print(f"Analyzing token: {mint[:8]}...")
    
    if not metadata or not isinstance(metadata, dict):
        return None
    
    # Extract basic info with safe navigation
    on_chain = metadata.get("onChainMetadata")
    if not on_chain or not isinstance(on_chain, dict):
        on_chain = {}
    
    metadata_obj = on_chain.get("metadata")
    if not metadata_obj or not isinstance(metadata_obj, dict):
        metadata_obj = {}
    
    token_info = metadata_obj.get("data")
    if not token_info or not isinstance(token_info, dict):
        token_info = {}
    
    name = str(token_info.get("name", "Unknown")).strip() if token_info.get("name") else "Unknown"
    symbol = str(token_info.get("symbol", "???")).strip() if token_info.get("symbol") else "???"
    
    # Skip if no valid name/symbol
    if name == "Unknown" or not symbol or symbol == "???":
        return None
    
    # Get token supply
    supply_info = get_token_supply(mint)
    total_supply = 0
    decimals = 9
    if supply_info and isinstance(supply_info, dict):
        total_supply = int(supply_info.get("amount", 0))
        decimals = int(supply_info.get("decimals", 9))
    
    # Get largest holders
    largest_accounts = get_token_largest_accounts(mint)
    holder_count = len(largest_accounts) if largest_accounts else 0
    
    # Calculate dev holdings (largest holder percentage)
    dev_holdings = 0.0
    if largest_accounts and total_supply > 0:
        largest_amount = int(largest_accounts[0].get("amount", 0))
        dev_holdings = (largest_amount / total_supply) * 100
    
    # Estimate age from metadata update time
    age_hours = 48.0  # Default estimate
    if "updatedAt" in on_chain:
        try:
            update_timestamp = on_chain["updatedAt"]
            if isinstance(update_timestamp, (int, float)):
                age_hours = (time.time() - update_timestamp) / 3600
        except:
            pass
    
    # Estimate liquidity (simplified - using holder count as proxy)
    # In production, you'd query DEX pool data
    liquidity = holder_count * 150  # Rough estimate
    
    # Calculate component scores
    holder_score = calculate_holder_score(holder_count)
    age_score = calculate_age_score(age_hours)
    dev_score = calculate_dev_holdings_score(dev_holdings)
    liquidity_score = calculate_liquidity_score(liquidity)
    
    # Calculate weighted total score
    total_score = (
        holder_score * WEIGHTS["holders"] +
        age_score * WEIGHTS["age"] +
        dev_score * WEIGHTS["dev_holdings"] +
        liquidity_score * WEIGHTS["liquidity"]
    )
    
    # Determine risk level
    if total_score >= 75:
        risk_level = "low"
    elif total_score >= 50:
        risk_level = "medium"
    else:
        risk_level = "high"
    
    # Generate flags
    flags = []
    
    if holder_count >= THRESHOLDS["excellent_holders"]:
        flags.append({"type": "opportunity", "text": f"Excellent holder base ({holder_count} holders)"})
    elif holder_count >= THRESHOLDS["good_holders"]:
        flags.append({"type": "opportunity", "text": f"Strong holder base ({holder_count} holders)"})
    elif holder_count < THRESHOLDS["min_holders"]:
        flags.append({"type": "high-risk", "text": f"Low holder count ({holder_count} holders)"})
    
    if THRESHOLDS["sweet_spot_age_min"] <= age_hours <= THRESHOLDS["sweet_spot_age_max"]:
        flags.append({"type": "opportunity", "text": f"In sweet spot age range ({age_hours:.1f}h)"})
    elif age_hours < 12:
        flags.append({"type": "medium-risk", "text": f"Very new token ({age_hours:.1f}h)"})
    elif age_hours > 168:
        flags.append({"type": "medium-risk", "text": f"Older token ({age_hours:.1f}h)"})
    
    if dev_holdings >= THRESHOLDS["dev_red_flag"]:
        flags.append({"type": "high-risk", "text": f"High dev holdings ({dev_holdings:.1f}%)"})
    elif dev_holdings >= THRESHOLDS["dev_warning"]:
        flags.append({"type": "medium-risk", "text": f"Moderate dev holdings ({dev_holdings:.1f}%)"})
    else:
        flags.append({"type": "low-risk", "text": f"Low dev holdings ({dev_holdings:.1f}%)"})
    
    if liquidity >= THRESHOLDS["great_liquidity"]:
        flags.append({"type": "opportunity", "text": f"Great liquidity (${liquidity:,.0f})"})
    elif liquidity < THRESHOLDS["min_liquidity"]:
        flags.append({"type": "high-risk", "text": f"Low liquidity (${liquidity:,.0f})"})
    
    return {
        "address": mint,
        "name": name,
        "symbol": symbol,
        "score": round(total_score, 2),
        "risk_level": risk_level,
        "holders": holder_count,
        "age_hours": round(age_hours, 2),
        "dev_holdings": round(dev_holdings, 2),
        "liquidity": round(liquidity, 2),
        "flags": flags
    }


def scan_tokens(max_tokens: int = 20) -> Dict[str, Any]:
    """Main scanning function"""
    print(f"\n{'='*60}")
    print("PUMP.FUN TOKEN SCANNER")
    print(f"{'='*60}\n")
    
    # Try DAS API first for finding pump.fun tokens
    mints = search_assets_by_creator(PUMP_FUN_PROGRAM, limit=max_tokens)
    
    # Fallback to transaction parsing if DAS fails
    if not mints:
        print("DAS search failed, falling back to transaction parsing...")
        transactions = fetch_recent_transactions(limit=100)
        if not transactions:
            print("No transactions found")
            return create_empty_result()
        
        mints = extract_token_mints(transactions)
        if not mints:
            print("No token mints found")
            return create_empty_result()
    
    # Limit number of tokens to analyze
    mints = mints[:max_tokens]
    
    # Fetch metadata in batch
    metadata_map = fetch_token_metadata_batch(mints)
    
    # Analyze tokens
    analyzed_tokens = []
    for mint in mints:
        metadata = metadata_map.get(mint, {})
        token_data = analyze_token(mint, metadata)
        if token_data:
            analyzed_tokens.append(token_data)
        time.sleep(0.1)  # Rate limiting
    
    # Sort by score
    analyzed_tokens.sort(key=lambda t: t["score"], reverse=True)
    
    # Calculate stats
    total_scanned = len(analyzed_tokens)
    opportunities = len([t for t in analyzed_tokens if t["score"] >= 70])
    avg_score = sum(t["score"] for t in analyzed_tokens) / total_scanned if total_scanned > 0 else 0
    total_liquidity = sum(t["liquidity"] for t in analyzed_tokens)
    
    print(f"\n{'='*60}")
    print("SCAN COMPLETE")
    print(f"{'='*60}")
    print(f"Total tokens scanned: {total_scanned}")
    print(f"Opportunities found: {opportunities}")
    print(f"Average score: {avg_score:.2f}")
    print(f"Total liquidity: ${total_liquidity:,.2f}")
    print(f"{'='*60}\n")
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_scanned": total_scanned,
            "opportunities": opportunities,
            "avg_score": round(avg_score, 2),
            "total_liquidity": round(total_liquidity, 2)
        },
        "tokens": analyzed_tokens
    }


def create_empty_result() -> Dict[str, Any]:
    """Create empty result structure"""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_scanned": 0,
            "opportunities": 0,
            "avg_score": 0,
            "total_liquidity": 0
        },
        "tokens": []
    }


def main():
    """Main entry point"""
    # Run scan
    results = scan_tokens(max_tokens=20)
    
    # Ensure data directory exists
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)
    
    # Write results
    output_file = output_dir / "tokens.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"Results written to: {output_file}")
    
    # Print top opportunities
    if results["tokens"]:
        print("\nTOP OPPORTUNITIES:\n")
        for i, token in enumerate(results["tokens"][:5], 1):
            print(f"{i}. {token['name']} ({token['symbol']})")
            print(f"   Score: {token['score']}/100 | Risk: {token['risk_level'].upper()}")
            print(f"   Holders: {token['holders']} | Age: {token['age_hours']:.1f}h")
            print(f"   Dev Holdings: {token['dev_holdings']:.1f}% | Liquidity: ${token['liquidity']:,.2f}")
            print(f"   Address: {token['address']}")
            if token['flags']:
                for flag in token['flags'][:3]:  # Limit to 3 most important flags
                    print(f"   - {flag['text']}")
            print()


if __name__ == "__main__":
    main()
