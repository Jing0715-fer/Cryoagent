        // 尝试解析为普通 JSON 响应
        try {
            const data = await response.json();
            // 支持新格式 (result) 和旧格式 (answer)
            if (data.success) {
                if (data.result) {
                    // 新格式：{'success': true, 'result': {type, content, image_url, ...}}
                    finalAnswer = data.result.content || '';
                    sources = data.result.sources || [];
                    imageUrl = data.result.image_url || null;
                    console.log('[QA.js] 使用新格式：content=', finalAnswer.substring(0, 50), 'imageUrl=', imageUrl);
                } else if (data.answer) {
                    // 旧格式：{'success': true, 'answer': ..., 'image_url': ...}
                    finalAnswer = data.answer;
                    sources = data.sources || [];
                    imageUrl = data.image_url || null;
                    console.log('[QA.js] 使用旧格式：content=', finalAnswer.substring(0, 50), 'imageUrl=', imageUrl);
                } else {
                    console.error('API 返回成功但没有内容:', data);
                }
                // 保存返回的 session_id
                if (data.session_id) {
                    currentSessionId = data.session_id;
                    localStorage.setItem('currentSessionId', currentSessionId);
                    console.log('Session ID:', currentSessionId);
                }
            } else {
                console.error('API 返回错误:', data);
                throw new Error(data.error || 'Unknown error');
            }
        } catch (e) {
            console.error('JSON parse error:', e);
            finalAnswer = '抱歉，处理响应时发生错误';
        }

        // 如果上面的 JSON 解析失败，尝试 SSE 流式处理作为 fallback
        if (!finalAnswer) {
