<template>
  <div class="mobile-layout">
    <div class="header-container">
      <van-search
        v-model="searchValue"
        placeholder="Search for something..."
        shape="round"
        background="#1989fa"
        input-align="center"
      />
    </div>

    <div class="main-content">
      <transition name="fade-transform" mode="out-in">
        <router-view />
      </transition>
    </div>

    <van-tabbar v-model="active" route :fixed="false" active-color="#6366f1" inactive-color="#969799">
      <van-tabbar-item replace to="/mobile/home" icon="home-o">首页</van-tabbar-item>
      <!-- <van-tabbar-item replace to="/mobile/mall" icon="shop-o">商城</van-tabbar-item> -->
      <van-tabbar-item replace to="/mobile/ai" icon="apps-o">AI Park</van-tabbar-item>
      <van-tabbar-item replace to="/mobile/ai-entrance">
        <template #icon="props">
          <svg :class="['custom-ai-icon', props.active ? 'active' : '']" viewBox="0 0 24 24" width="24" height="24" fill="none">
            <!-- 机器人头部 -->
            <rect x="4" y="5" width="16" height="13" rx="3" stroke="currentColor" stroke-width="1.8" fill="none" />
            <!-- 天线 -->
            <line x1="12" y1="2" x2="12" y2="5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            <circle cx="12" cy="1.5" r="1.2" fill="currentColor" />
            <!-- 眼睛 -->
            <circle cx="9" cy="11" r="1.4" fill="currentColor" />
            <circle cx="15" cy="11" r="1.4" fill="currentColor" />
            <!-- 嘴巴/显示屏 -->
            <rect x="8" y="14.5" width="8" height="2.5" rx="1" stroke="currentColor" stroke-width="1.5" fill="none" />
            <!-- 耳朵 -->
            <rect x="2" y="9" width="2.5" height="3" rx="1" stroke="currentColor" stroke-width="1.5" fill="none" />
            <rect x="19.5" y="9" width="2.5" height="3" rx="1" stroke="currentColor" stroke-width="1.5" fill="none" />
          </svg>
        </template>
        AI
      </van-tabbar-item>
      <van-tabbar-item replace to="/mobile/message" icon="chat-o">消息</van-tabbar-item>
      <van-tabbar-item replace to="/mobile/me" icon="user-o">我的</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script>
export default {
  name: 'MobileLayout',
  data() {
    return {
      active: 0,
      searchValue: ''
    }
  }
}
</script>

<style scoped>
/* 关键：整个容器铺满视口高度，用 flex 纵向布局 */
.mobile-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: #f7f8fa;
  overflow: hidden;
}

/* 顶部搜索栏：固定不压缩 */
.header-container {
  flex-shrink: 0;
  z-index: 999;
}

/* 核心：main-content 占满剩余高度，自己处理滚动 */
.main-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  /* 子页面如果要铺满，可以用 margin: -10px 抵消这个 padding */
  padding: 10px;
  /* 让子元素的 height: 100% 生效 */
  position: relative;
}

/* 底部 tabbar：固定不压缩（已设 fixed=false，现在是 flex 子项） */
::v-deep .van-tabbar {
  flex-shrink: 0;
}
.custom-ai-icon {
  color: #969799;
  transition: color 0.2s;
}
.custom-ai-icon.active {
  color: #6366f1;
}
</style>
