# Local Setup

1. Install dependencies:

```bash
devops/scripts/install_dependencies.sh
```

2. Create local runtime env:

```bash
cp .env.example .env
```

3. Start local services:

```bash
docker compose -f docker-compose.dev.yml up --build
```

Never commit `.env`. Runtime secrets such as `BONBON_JWT_SECRET` and `BONBON_ADMIN_PASSWORD` belong only on deployment hosts or CI secret stores.
