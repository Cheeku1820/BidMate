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
    "/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
    "21_1001_unalaska_library_cd_biddrawings.pdf",
)
