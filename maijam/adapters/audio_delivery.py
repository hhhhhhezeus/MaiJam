"""Conservative audio capability boundary. No fake chat delivery is claimed."""


def delivery_status():
    return {'sent': False, 'supported': False,
            'message': '当前 SDK 没有已验证的通用音频发送接口。文件已保存在插件数据目录，需由部署者从宿主机获取。'}
