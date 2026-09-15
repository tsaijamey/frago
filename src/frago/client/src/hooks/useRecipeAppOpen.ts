/**
 * 服务端请界面打开某个配方的页面时，切过去。
 *
 * 配方跑完带着 `open_url`、或者有人敲了 `frago recipe open`，服务端不再直接叫系统
 * 浏览器开新标签，而是先推一条 `recipe_app_open` 给开着的界面：这边把页面 pin 到
 * recipes 下面、切到右侧打开，然后回一句「开了」。服务端两秒内没收到回话，才自己
 * 开浏览器（开的也是界面的地址）。
 */

import { useCallback } from 'react';
import { useWebSocket } from './useWebSocket';
import { MessageType, type WebSocketMessage } from '@/api/websocket';
import { ackRecipeAppShow } from '@/api/client';
import { usePageStore } from '@/stores/pageStore';
import { recipeAppId, useRecipeAppPins } from '@/stores/recipeAppPins';

export function useRecipeAppOpen(): void {
  const handleMessage = useCallback((message: WebSocketMessage) => {
    if (message.type !== MessageType.RECIPE_APP_OPEN) return;
    const data = message.data as { name?: string; slot?: string | null; request_id?: string } | undefined;
    if (!data?.name) return;

    // 这个配方已经开着，就回到已开的那一张，不换地址、不重新载入——那上面可能有人
    // 还没保存的输入。没开着才按推过来的地址 pin 上。
    const id = useRecipeAppPins.getState().pin(recipeAppId(data.name, data.slot));
    usePageStore.getState().switchPage('recipe_app', id);

    if (data.request_id) {
      ackRecipeAppShow(data.request_id).catch(() => {
        // 回话丢了，服务端会再开一个浏览器标签——多一个标签，不丢页面
      });
    }
  }, []);

  useWebSocket({ messageTypes: [MessageType.RECIPE_APP_OPEN], onMessage: handleMessage });
}
