import docker
import re

client = docker.from_env()

DOCKER_NETWORK = "project_nightscout_net"
NIGHTSCOUT_IMAGE = "nightscout/cgm-remote-monitor:latest"
NIGHTSCOUT_PORT = 1337

def _slugify(text):
    """تحويل النص (اسم المستخدم) لصيغة آمنة للدومين والدوال"""
    return re.sub(r'[^a-zA-Z0-9\-]', '-', text.lower())

def create_nightscout_instance(instance_name, subdomain, mongo_uri, api_secret, extra_env=None):
    """
    ينشئ حاوية Nightscout جديدة مع ربط Traefik ودومين فرعي ديناميكي
    :param instance_name: اسم الحاوية (يفضل يكون فريد للمستخدم)
    :param subdomain: اسم الدومين الفرعي للمستخدم
    :param mongo_uri: رابط قاعدة بيانات مونجو الخاصة بالمستخدم
    :param api_secret: كلمة سر مثيل Nightscout (تساوي كلمة سر المستخدم)
    :param extra_env: متغيرات بيئية إضافية (اختياري)
    :return: كائن الحاوية (أو Exception)
    """
    try:
        safe_subdomain = _slugify(subdomain)
        safe_instance = _slugify(instance_name)

        # احذف أي حاوية بنفس الاسم إذا كانت موجودة
        try:
            existing = client.containers.get(safe_instance)
            existing.stop()
            existing.remove()
        except docker.errors.NotFound:
            pass

        labels = {
            "traefik.enable": "true",
            f"traefik.http.routers.ns-{safe_subdomain}.rule": f"Host(`{safe_subdomain}.nst1d.com`)",
            f"traefik.http.services.ns-{safe_subdomain}.loadbalancer.server.port": str(NIGHTSCOUT_PORT),
            "traefik.docker.network": DOCKER_NETWORK,
        }

        env = {
            "MONGO_CONNECTION": mongo_uri,
            "API_SECRET": api_secret,
            "PORT": str(NIGHTSCOUT_PORT),
            "INSECURE_USE_HTTP": "true",
        }
        if extra_env:
            env.update(extra_env)

        container = client.containers.run(
            NIGHTSCOUT_IMAGE,
            name=safe_instance,
            detach=True,
            environment=env,
            labels=labels,
            network=DOCKER_NETWORK,
            restart_policy={"Name": "always"},
            ports={"1337/tcp": None},
        )
        return container
    except Exception as e:
        print(f"[docker_utils] Error creating Nightscout instance: {e}")
        raise

def delete_nightscout_instance(instance_name):
    """
    حذف مثيل Nightscout حسب اسم الحاوية
    """
    try:
        safe_instance = _slugify(instance_name)
        container = client.containers.get(safe_instance)
        container.stop()
        container.remove()
        return True
    except docker.errors.NotFound:
        return False
    except Exception as e:
        print(f"[docker_utils] Error deleting Nightscout instance: {e}")
        return False
