"""The real bid set the engine's regression tests measure against.

Overridable so these are not machine-local: the assertions they carry are
the only guards on a defect that silently zeroed 43 of 45 items, and a
hardcoded personal path makes them a no-op everywhere else. Three test
modules held three copies of that path, each behind
`skipif(not os.path.exists(BID))`, so on any other checkout -- and in any
CI that ever gets added -- every one of those guards passed by not running.

Set BIDMATE_BID_SET to point the engine regression tests at a local copy.
"""

import os

BID = os.environ.get(
    "BIDMATE_BID_SET",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "bid_examples", "Unalaska Bid", "21_1001_unalaska_library_cd_biddrawings.pdf",
    ),
)

CORPUS = os.environ.get(
    "BIDMATE_CORPUS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bid_examples"),
)

# The electrical PDF of each vector set, keyed by fixture name.
VECTOR_SETS = {
    "unalaska": "Unalaska Bid/21_1001_unalaska_library_cd_biddrawings.pdf",
    "kittles_saxony": "Kittles Saxony/PLANS/Electrical Plans.pdf",
    "pulte_sagebriar": "Pulte Sagebriar Clubhouse/PLANS/20250124 - Sagebriar - Permit_Bid - Electrical.pdf",
    "tsc_nutrition": "TSC Nutrition & Technology Renovations/PLANS/2025-0604_Nutrition___Technology_100__CD_Set.pdf",
    "united_utility": "United Utility Supply/PLANS/0_DRAWING SET_UUS_BID DOCUMENTS_20260608_2.pdf",
}

# Raster sets: every detected page must carry unreadable_reason.
RASTER_SETS = {
    "fedex": "FedEx Office Bid/FedEx Office.pdf",
    "gerber": "Gerber Collision & Glass Bid/Renovation for Gerber Collision & Glass (1).pdf",
}


def corpus_path(rel: str) -> str:
    return os.path.join(CORPUS, rel)
