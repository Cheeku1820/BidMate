"""The estimator-facing strings a job can end with (spec §9). One
definition each: the worker writes them into `documents.error` and
`jobs.error`, screens C and E read them back, and the tests assert them
verbatim. Never an exception class name, never a model name."""

ENCRYPTED = "Couldn't read — the file is password protected. Upload an unlocked copy."
UNREADABLE = "Couldn't read this file. Try re-saving it as PDF from the original and uploading again."
UNAVAILABLE = "Couldn't open this file right now. Try again in a few minutes."
SHEET_UNREADABLE = "This sheet couldn't be read."
SHEET_FAILED = "This sheet couldn't be processed. Start the takeoff again to retry it."
SCHEDULES_UNCHECKED = "Schedules weren't checked on this sheet."
NO_DRAWINGS = "No drawings have been read yet. Upload a drawing set, or wait for reading to finish."
NON_PLAN = "Schedule or legend — no devices counted."
PAGE_GONE = "This page is no longer in the uploaded file."
