# api/

Every call to the FastAPI backend lives here, one function per call. Pages call
these functions and never build URLs themselves. The TypeScript types for each
response will be generated from the backend's schema, so they always match the
Python models.

Empty until the backend exists.
