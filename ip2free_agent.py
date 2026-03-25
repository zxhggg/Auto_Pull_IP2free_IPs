import json
from pathlib import Path

import requests

# 配置信息
API_URL = "https://api.ip2free.com"
HEADERS = {
    "webname": "IP2FREE",
    "domain": "www.ip2free.com",
    "lang": "cn",
    "referer": "https://www.ip2free.com/",
    "origin": "https://www.ip2free.com",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "content-type": "text/plain;charset=UTF-8",
}
ENV_FILE = Path(__file__).with_name(".env")
SUPPORTED_PROXY_SOURCES = {"free", "activity", "both"}
SUPPORTED_OUTPUT_FORMATS = {"yaml", "txt"}


class AppConfig:
    """读取 .env 配置文件"""

    def __init__(self, values=None):
        self.values = values or {}

    @classmethod
    def load(cls, env_path=None):
        env_path = Path(env_path or ENV_FILE)
        values = {}

        if env_path.exists():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]

                values[key] = value

        return cls(values)

    def get(self, key, default=None):
        value = self.values.get(key)
        if value is None or value == "":
            return default
        return value

    def get_bool(self, key, default=True):
        value = self.get(key)
        if value is None:
            return default
        return str(value).strip().lower() not in {"0", "false", "no", "off"}


class IP2FreeClient:
    def __init__(self, config=None):
        self.config = config or AppConfig.load()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.token = None

    def check_credentials(self):
        """检查登录信息"""
        email = self.config.get("IP2FREE_EMAIL")
        password = self.config.get("IP2FREE_PASSWORD")
        if not email or not password:
            raise Exception("请先在 .env 文件中设置 IP2FREE_EMAIL 和 IP2FREE_PASSWORD")
        return email, password

    def get_proxy_source_mode(self):
        """读取代理来源模式"""
        value = str(self.config.get("IP2FREE_PROXY_SOURCE", "")).strip().lower()
        if value in SUPPORTED_PROXY_SOURCES:
            return value

        # 兼容旧配置
        if self.config.get_bool("IP2FREE_INCLUDE_ACTIVITY_IPS", default=True):
            return "both"
        return "free"

    def get_output_format(self):
        """读取输出格式"""
        value = str(self.config.get("IP2FREE_OUTPUT_FORMAT", "yaml")).strip().lower()
        if value not in SUPPORTED_OUTPUT_FORMATS:
            raise Exception(
                f"IP2FREE_OUTPUT_FORMAT 配置无效: {value}，仅支持 {', '.join(sorted(SUPPORTED_OUTPUT_FORMATS))}"
            )
        return value

    def _post_json(self, endpoint, data=None, timeout=30, allow_business_error=False):
        """发送POST请求并返回JSON结果"""
        response = self.session.post(
            f"{API_URL}/api{endpoint}",
            data=json.dumps(data or {}),
            timeout=timeout,
        )
        response.raise_for_status()

        result = response.json()
        code = result.get("code", 0)
        if code != 0 and not allow_business_error:
            raise Exception(result.get("msg") or f"请求失败: {endpoint} (code={code})")
        return result

    @staticmethod
    def _safe_int(value, default=0):
        """安全转换整数"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _normalize_proxy(self, proxy, source):
        """统一整理代理数据，兼容活动代理返回格式"""
        normalized = dict(proxy)
        contents = normalized.get("contents")

        if contents and normalized.get("provider_id") == 1:
            try:
                parsed = json.loads(contents)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    normalized.update(parsed[0])
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        normalized["source"] = source
        normalized["expires_at"] = normalized.get("expires_at") or normalized.get("expired_at")
        return normalized

    def _build_proxy_identity(self, proxy, index):
        """构建统一代理信息"""
        return {
            "source": proxy.get("source", "free"),
            "country": proxy.get("country_code") or proxy.get("country") or "XX",
            "city": str(proxy.get("city") or "unknown").replace(" ", "_"),
            "proxy_id": proxy.get("id") or proxy.get("task_id") or proxy.get("source_id") or index,
            "protocol": (proxy.get("protocol") or "socks5").lower(),
            "server": proxy.get("ip") or proxy.get("host") or "",
            "port": self._safe_int(proxy.get("port"), 0),
            "username": proxy.get("username") or "",
            "password": proxy.get("password") or "",
        }

    def login(self):
        """登录获取token"""
        email, password = self.check_credentials()

        result = self._post_json(
            "/account/login",
            data={
                "email": email,
                "password": password,
            },
        )
        self.token = result.get("data", {}).get("token") or self.session.cookies.get("Mall-Token")

        if not self.token:
            raise Exception("登录失败，未获取到 token")

        self.session.headers["x-token"] = self.token
        self.session.headers["X-Token"] = self.token
        self.session.cookies.set("Mall-Token", self.token, domain="www.ip2free.com", path="/")

        print("登录成功")
        return True

    def get_task_list(self):
        """获取活动任务列表"""
        if not self.token:
            self.login()

        result = self._post_json("/account/taskList", data={})
        data = result.get("data", {}) or {}
        task_list = data.get("list", []) or []

        print(
            f"获取到 {len(task_list)} 个活动任务 "
            f"(邀请进度: {data.get('register_count', 0)}, 订单进度: {data.get('order_count', 0)})"
        )
        return data

    def claim_activity_rewards(self, task_name_contains=None):
        """自动领取可直接点击领取的活动奖励"""
        task_data = self.get_task_list()
        task_list = task_data.get("list", []) or []

        candidates = []
        for task in task_list:
            task_name = task.get("task_name", "")
            task_code = task.get("task_code", "")
            if task_name_contains and task_name_contains not in task_name:
                continue
            if task.get("is_finished") == 1:
                continue
            if task_code == "client_click":
                candidates.append(task)

        if not candidates:
            print("没有需要自动领取的活动奖励")
            return []

        print(f"发现 {len(candidates)} 个可自动领取的活动奖励")
        results = []

        for task in candidates:
            task_name = task.get("task_name", f"task#{task.get('id', 'unknown')}")
            task_id = task.get("id")
            if not task_id:
                print(f"跳过任务，缺少 id: {task_name}")
                continue

            result = self._post_json(
                "/account/finishTask",
                data={"id": task_id},
                allow_business_error=True,
            )
            code = result.get("code", -999)
            msg = result.get("msg") or ""

            if code == 0:
                status = "claimed"
                print(f"领取成功: {task_name}")
            elif code == -1:
                status = "already-done"
                print(f"任务已完成或已领取: {task_name} ({msg or 'code=-1'})")
            else:
                status = "failed"
                print(f"领取失败: {task_name} ({msg or f'code={code}'})")

            results.append(
                {
                    "task_id": task_id,
                    "task_name": task_name,
                    "task_code": task.get("task_code"),
                    "status": status,
                    "code": code,
                    "message": msg,
                }
            )

        return results

    def get_free_proxies(self):
        """获取免费代理列表"""
        if not self.token:
            self.login()

        all_proxies = []
        page = 1
        page_size = 100

        while True:
            result = self._post_json(
                "/ip/freeList",
                data={
                    "keyword": "",
                    "country": "",
                    "city": "",
                    "page": page,
                    "page_size": page_size,
                },
            )
            proxy_list = result.get("data", {}).get("free_ip_list", []) or []

            if not proxy_list:
                break

            all_proxies.extend(self._normalize_proxy(proxy, source="free") for proxy in proxy_list)

            if len(proxy_list) < page_size:
                break

            page += 1
            if page > 10:
                break

        if not all_proxies:
            raise Exception("没有获取到可用的免费代理")

        print(f"获取到 {len(all_proxies)} 个免费代理")
        return all_proxies

    def get_activity_proxies(self):
        """获取活动奖励代理列表"""
        if not self.token:
            self.login()

        all_proxies = []
        page = 1
        page_size = 100

        while True:
            result = self._post_json(
                "/ip/taskIpList",
                data={
                    "keyword": "",
                    "country": "",
                    "city": "",
                    "page": page,
                    "page_size": page_size,
                },
                allow_business_error=True,
            )
            if result.get("code") not in (0, None):
                message = result.get("msg") or f"code={result.get('code')}"
                print(f"活动代理接口返回: {message}")
                break

            page_data = result.get("data", {}).get("page", {}) or {}
            proxy_list = page_data.get("list", []) or []

            if not proxy_list:
                break

            all_proxies.extend(self._normalize_proxy(proxy, source="activity") for proxy in proxy_list)

            total_row = self._safe_int(page_data.get("totalRow"))
            if len(proxy_list) < page_size:
                break
            if total_row and len(all_proxies) >= total_row:
                break

            page += 1
            if page > 10:
                break

        print(f"获取到 {len(all_proxies)} 个活动代理")
        return all_proxies

    def create_clash_config(self, proxies):
        """生成 Clash YAML 配置"""
        proxy_configs = []
        proxy_names = []

        for index, proxy in enumerate(proxies, start=1):
            item = self._build_proxy_identity(proxy, index)
            if not item["server"] or not item["port"]:
                continue

            name = f"ip2free_{item['source']}_{item['country']}_{item['city']}_{item['proxy_id']}"
            proxy_configs.append(
                f'''  - name: "{name}"
    type: {item['protocol']}
    server: {item['server']}
    port: {item['port']}
    username: {item['username']}
    password: {item['password']}
'''
            )
            proxy_names.append(name)

        if not proxy_configs:
            raise Exception("没有可写入 Clash 配置的代理数据")

        proxy_group = """proxy-groups:
  - name: "自动选择"
    type: select
    proxies:
"""
        for name in proxy_names:
            proxy_group += f'      - "{name}"\n'
        proxy_group += "      - DIRECT\n"

        return f"""port: 7890
socks-port: 7891
mode: rule
allow-lan: false
log-level: info

proxies:
{''.join(proxy_configs)}
{proxy_group}
rules:
  - MATCH,自动选择

dns:
  enabled: true
  listen: 0.0.0.0:1053
  default-nameserver:
    - 1.1.1.1
    - 8.8.8.8
  nameserver:
    - 1.1.1.1
    - 8.8.8.8
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  use-hosts: true
"""

    def create_txt_config(self, proxies):
        """生成 txt 代理列表，一行一个代理"""
        lines = []
        for index, proxy in enumerate(proxies, start=1):
            item = self._build_proxy_identity(proxy, index)
            if not item["server"] or not item["port"]:
                continue

            line = f"{item['protocol']}://{item['server']}:{item['port']}"
            if item["username"] or item["password"]:
                line += f":{item['username']}:{item['password']}"
            lines.append(line)

        if not lines:
            raise Exception("没有可写入 TXT 的代理数据")

        return "\n".join(lines) + "\n"

    def get_save_path(self, output_format):
        """获取输出文件保存路径"""
        file_name = "proxies.yaml" if output_format == "yaml" else "proxies.txt"
        custom_path = self.config.get("IP2FREE_CONFIG_PATH")

        if custom_path:
            if custom_path == ".":
                save_dir = Path.cwd()
            elif custom_path.startswith("."):
                save_dir = Path.cwd() / custom_path
            else:
                save_dir = Path(custom_path).expanduser()
            print(f"使用自定义保存路径: {save_dir}")
        else:
            desktop = Path.home() / "Desktop"
            save_dir = desktop / "proxy"
            print(f"使用默认保存路径: {save_dir}")

        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / file_name

    def save_output(self, content, output_format):
        """保存输出文件"""
        config_file = self.get_save_path(output_format)
        config_file.write_text(content, encoding="utf-8")
        print(f"{output_format.upper()} 文件已保存到: {config_file}")
        return config_file


def main():
    """主函数"""
    try:
        print("开始获取 IP2FREE 代理...")

        config = AppConfig.load()
        client = IP2FreeClient(config=config)
        output_format = client.get_output_format()
        proxy_source_mode = client.get_proxy_source_mode()

        print(f"代理来源模式: {proxy_source_mode}")
        print(f"导出格式: {output_format}")

        client.login()

        if client.config.get_bool("IP2FREE_AUTO_CLAIM_REWARDS", default=True):
            task_name_filter = client.config.get("IP2FREE_ACTIVITY_TASK_NAME_CONTAINS")
            client.claim_activity_rewards(task_name_contains=task_name_filter)
        else:
            print("已跳过自动领取活动奖励")

        proxies = []

        if proxy_source_mode in {"free", "both"}:
            free_proxies = client.get_free_proxies()
            proxies.extend(free_proxies)
        else:
            print("已跳过免费代理")

        if proxy_source_mode in {"activity", "both"}:
            activity_proxies = client.get_activity_proxies()
            proxies.extend(activity_proxies)
        else:
            print("已跳过活动代理")

        print(f"总计写入 {len(proxies)} 个代理")

        if output_format == "yaml":
            output_text = client.create_clash_config(proxies)
        else:
            output_text = client.create_txt_config(proxies)

        client.save_output(output_text, output_format)

        print("操作完成！")
    except Exception as e:
        print(f"出错了: {e}")
        return False

    return True


if __name__ == "__main__":
    main()
