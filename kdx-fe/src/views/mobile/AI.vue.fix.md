## 问题分析

从截图可以看到：
1. 后端上传接口返回了成功（code: 200）
2. 但前端页面仍然显示"请先上传您的人脸照片"

## 根本原因

在 `handleImageSelect` 方法中，上传成功后虽然设置了 `this.hasFace = true`，但由于 Vue 的响应式系统可能没有正确检测到这个变化，导致页面没有重新渲染。

## 修复方案

需要确保状态更新后 Vue 能够正确检测到变化。可以通过以下方式修复：

1. 使用 `$forceUpdate()` 强制重新渲染
2. 或者使用 Vue.set() 确保响应式更新

## 具体修复

在 `handleImageSelect` 方法中，上传成功后添加 `this.$forceUpdate()`：

```javascript
async handleImageSelect(event) {
  // ... 省略其他代码 ...
  
  try {
    const faceUrl = await this.uploadToMinIO(file)

    const response = await this.$axios.post('/face/upload', {
      face_url: faceUrl
    })

    if (response.data && response.data.code === 200) {
      Toast.success('人脸照片上传成功')
      
      // 使用 Vue.set 确保响应式更新
      this.$set(this, 'hasFace', true)
      this.$set(this, 'faceStatus', 'uploaded')
      this.$set(this, 'recognitionResult', null)
      
      // 强制重新渲染
      this.$forceUpdate()
      
      // 可选：重新检查人脸状态确保一致性
      setTimeout(() => {
        this.checkFaceInfo()
      }, 500)
    } else {
      Toast.fail(response.data.msg || '上传失败')
      this.faceStatus = 'idle'
    }
  } catch (error) {
    Toast.fail('上传失败，请重试')
    this.faceStatus = 'idle'
  }

  event.target.value = ''
},
```

## 额外建议

为了更好地调试和监控状态变化，可以添加调试日志：

```javascript
if (response.data && response.data.code === 200) {
  Toast.success('人脸照片上传成功')
  console.log('上传成功，更新状态前:', { hasFace: this.hasFace, faceStatus: this.faceStatus })
  
  this.$set(this, 'hasFace', true)
  this.$set(this, 'faceStatus', 'uploaded')
  this.$set(this, 'recognitionResult', null)
  
  console.log('上传成功，更新状态后:', { hasFace: this.hasFace, faceStatus: this.faceStatus })
  
  this.$forceUpdate()
}
```

这样可以在浏览器控制台中查看状态是否正确更新。

## 总结

问题的核心是 Vue 响应式系统可能没有正确检测到 `hasFace` 属性的变化。通过使用 `Vue.set()` 和 `$forceUpdate()` 可以确保状态更新后页面正确重新渲染。
