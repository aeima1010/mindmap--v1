import uvicorn
import os
from api.index import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("api.index:app", host="0.0.0.0", port=port)
