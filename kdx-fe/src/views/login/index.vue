<template>
  <div class="login-container">
    <!-- 登录卡片 -->
    <div class="login-card">
      <!-- Logo区域 -->
      <div class="logo-section">
        <div class="logo">
          <svg viewBox="0 0 64 64" class="logo-icon">
            <defs>
              <linearGradient id="logoGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#667eea;stop-opacity:1" />
                <stop offset="100%" style="stop-color:#764ba2;stop-opacity:1" />
              </linearGradient>
            </defs>
            <rect x="4" y="4" width="56" height="56" rx="12" fill="url(#logoGradient)" />
            <text x="32" y="42" text-anchor="middle" font-size="24" font-weight="bold" fill="white">KDX</text>
          </svg>
        </div>
        <h1 class="title">欢迎回来</h1>
        <p class="subtitle">请登录您的账户</p>
      </div>

      <!-- 表单区域 -->
      <el-form
        ref="loginForm"
        :model="loginForm"
        :rules="loginRules"
        class="login-form"
        autocomplete="on"
        label-position="left"
      >
        <el-form-item prop="username">
          <div class="input-wrapper">
            <span class="input-icon">
              <i class="el-icon-user" />
            </span>
            <el-input
              ref="username"
              v-model="loginForm.username"
              placeholder="手机号"
              name="username"
              type="text"
              tabindex="1"
              autocomplete="on"
            />
          </div>
        </el-form-item>

        <el-tooltip v-model="capsTooltip" content="Caps lock is On" placement="right" manual>
          <el-form-item prop="password">
            <div class="input-wrapper">
              <span class="input-icon">
                <i class="el-icon-lock" />
              </span>
              <el-input
                :key="passwordType"
                ref="password"
                v-model="loginForm.password"
                :type="passwordType"
                placeholder="密码"
                name="password"
                tabindex="2"
                autocomplete="on"
                @keyup.native="checkCapslock"
                @blur="capsTooltip = false"
                @keyup.enter.native="handleLogin"
              />
              <span class="show-pwd" @click="showPwd">
                <i :class="passwordType === 'password' ? 'el-icon-eye' : 'el-icon-eye-off'" />
              </span>
            </div>
          </el-form-item>
        </el-tooltip>

        <div class="form-options">
          <el-checkbox v-model="rememberMe" class="remember-checkbox">记住密码</el-checkbox>
          <el-button type="text" class="forgot-btn">忘记密码?</el-button>
        </div>

        <el-button
          :loading="loading"
          type="primary"
          class="login-btn"
          @click.native.prevent="handleLogin"
        >
          {{ loading ? '登录中...' : '登 录' }}
        </el-button>
      </el-form>

      <!-- 注册链接 -->
      <div class="register-link">
        <span>还没有账户?</span>
        <el-button type="text" @click="showSignUpDialog = true">立即注册</el-button>
      </div>
    </div>

    <!-- 注册弹窗 -->
    <el-dialog title="注册账户" :visible.sync="showSignUpDialog" :width="dialogWidth" center append-to-body custom-class="signup-dialog">
      <SignUp :parent-sign-up-dialog="showSignUpDialog" @updateSignUpDialog="updateSignUpDialog" />
    </el-dialog>
  </div>
</template>

<script>
import SignUp from './components/SignUp.vue'
import Cookies from 'js-cookie'

export default {
  name: 'Login',
  components: { SignUp },
  data() {
    const validateUsername = (rule, value, callback) => {
      if (!value) {
        callback(new Error('请输入手机号'))
      } else {
        callback()
      }
    }
    const validatePassword = (rule, value, callback) => {
      if (value.length < 6) {
        callback(new Error('密码不能少于6位'))
      } else {
        callback()
      }
    }
    return {
      loginForm: {
        username: '',
        password: ''
      },
      loginRules: {
        username: [{ required: true, trigger: 'blur', validator: validateUsername }],
        password: [{ required: true, trigger: 'blur', validator: validatePassword }]
      },
      passwordType: 'password',
      capsTooltip: false,
      loading: false,
      showSignUpDialog: false,
      redirect: undefined,
      otherQuery: {},
      rememberMe: false,
      dialogWidth: '90%'
    }
  },
  watch: {
    $route: {
      handler: function(route) {
        const query = route.query
        if (query) {
          this.redirect = query.redirect
          this.otherQuery = this.getOtherQuery(query)
        }
      },
      immediate: true
    }
  },
  created() {
    this.getCookie()
  },
  mounted() {
    this.updateDialogWidth()
    window.addEventListener('resize', this.updateDialogWidth)
    if (this.loginForm.username === '') {
      this.$refs.username.focus()
    } else if (this.loginForm.password === '') {
      this.$refs.password.focus()
    }
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.updateDialogWidth)
  },
  methods: {
    updateDialogWidth() {
      this.dialogWidth = window.innerWidth > 480 ? '380px' : '90%'
    },
    getCookie() {
      const username = Cookies.get('username')
      const password = Cookies.get('password')
      const rememberMe = Cookies.get('rememberMe')
      this.loginForm = {
        username: username === undefined ? this.loginForm.username : username,
        password: password === undefined ? this.loginForm.password : window.atob(password)
      }
      this.rememberMe = rememberMe === undefined ? false : Boolean(rememberMe)
    },
    updateSignUpDialog(newValue) {
      this.showSignUpDialog = newValue
    },
    checkCapslock(e) {
      const { key } = e
      this.capsTooltip = key && key.length === 1 && (key >= 'A' && key <= 'Z')
    },
    showPwd() {
      this.passwordType = this.passwordType === 'password' ? '' : 'password'
      this.$nextTick(() => {
        this.$refs.password.focus()
      })
    },
    handleLogin() {
      this.$refs.loginForm.validate(valid => {
        if (valid) {
          this.loading = true
          if (this.rememberMe) {
            Cookies.set('username', this.loginForm.username, { expires: 30 })
            Cookies.set('password', window.btoa(this.loginForm.password), { expires: 30 })
            Cookies.set('rememberMe', this.rememberMe, { expires: 30 })
          } else {
            Cookies.remove('username')
            Cookies.remove('password')
            Cookies.remove('rememberMe')
          }
          this.$store.dispatch('user/login', this.loginForm)
            .then(() => {
              this.$router.push({ path: this.redirect || '/baby/details', query: this.otherQuery })
              this.loading = false
            })
            .catch(() => {
              this.loading = false
            })
        } else {
          console.log('error submit!!')
          return false
        }
      })
    },
    getOtherQuery(query) {
      return Object.keys(query).reduce((acc, cur) => {
        if (cur !== 'redirect') {
          acc[cur] = query[cur]
        }
        return acc
      }, {})
    }
  }
}
</script>

<style lang="scss">
$primary-color: #667eea;
$secondary-color: #764ba2;
$card-bg: #ffffff;
$text-primary: #2d3748;
$text-secondary: #718096;
$border-color: #e2e8f0;
$input-bg: #f7fafc;

.login-container {
  min-height: 100vh;
  width: 100%;
  background: #f5f7fa;
  display: flex;
  align-items: flex-start;
  justify-content: center;

  .login-card {
    width: 100%;
    max-width: 420px;
    min-height: 100vh;
    background: $card-bg;
    padding: 60px 30px 40px;
    animation: slideUp 0.6s ease-out;

    .logo-section {
      text-align: center;
      margin-bottom: 35px;

      .logo {
        width: 80px;
        height: 80px;
        margin: 0 auto 20px;
        border-radius: 20px;
        background: linear-gradient(135deg, $primary-color, $secondary-color);
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);

        .logo-icon {
          width: 50px;
          height: 50px;
        }
      }

      .title {
        font-size: 28px;
        font-weight: 700;
        color: $text-primary;
        margin: 0 0 8px;
      }

      .subtitle {
        font-size: 14px;
        color: $text-secondary;
        margin: 0;
      }
    }

    .login-form {
      .input-wrapper {
        position: relative;
        background: $input-bg;
        border-radius: 12px;
        border: 2px solid transparent;
        transition: all 0.3s ease;

        &:focus-within {
          border-color: $primary-color;
          background: white;
          box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .input-icon {
          position: absolute;
          left: 16px;
          top: 50%;
          transform: translateY(-50%);
          color: $text-secondary;
          font-size: 18px;
        }

        .el-input {
          width: 100%;

          input {
            padding-left: 50px;
            background: transparent;
            border: none;
            border-radius: 12px;
            height: 48px;
            font-size: 15px;
            color: $text-primary;
          }
        }

        .show-pwd {
          position: absolute;
          right: 16px;
          top: 50%;
          transform: translateY(-50%);
          color: $text-secondary;
          cursor: pointer;
          font-size: 18px;
          transition: color 0.3s ease;

          &:hover {
            color: $primary-color;
          }
        }
      }

      .form-options {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin: 20px 0;

        .remember-checkbox {
          font-size: 14px;
          color: $text-secondary;

          .el-checkbox__label {
            color: $text-secondary;
          }
        }

        .forgot-btn {
          font-size: 14px;
          color: $primary-color;
          padding: 0;

          &:hover {
            color: $secondary-color;
          }
        }
      }

      .login-btn {
        width: 100%;
        height: 50px;
        border-radius: 12px;
        background: linear-gradient(135deg, $primary-color, $secondary-color);
        border: none;
        font-size: 16px;
        font-weight: 600;
        color: white;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        transition: all 0.3s ease;

        &:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
        }

        &:active:not(:disabled) {
          transform: translateY(0);
        }
      }
    }

    .register-link {
      text-align: center;
      margin-top: 25px;
      font-size: 14px;
      color: $text-secondary;

      .el-button {
        padding: 0 8px;
        font-size: 14px;
        color: $primary-color;
        font-weight: 500;

        &:hover {
          color: $secondary-color;
        }
      }
    }
  }
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media screen and (max-width: 480px) {
  .login-container .login-card {
    padding: 30px 25px;
  }
}

.signup-dialog {
  width: 90% !important;
  max-width: 380px !important;
  border-radius: 16px;
  overflow: hidden;
  margin: auto;
  top: 50%;
  transform: translateY(-50%);
  max-height: 90vh;
  overflow-y: auto;

  ::v-deep .el-dialog__body {
    padding: 0;
    margin: 0;
    max-height: calc(90vh - 60px);
    overflow-y: auto;
  }

  ::v-deep .el-dialog__header {
    padding: 18px 20px 12px;
    text-align: center;
    border-bottom: 1px solid #f0f0f0;
    background: white;
    position: sticky;
    top: 0;
    z-index: 10;

    .el-dialog__title {
      font-size: 18px;
      font-weight: 600;
      color: #2d3748;
    }

    .el-dialog__close {
      font-size: 18px;
      color: #999;

      &:hover {
        color: #667eea;
      }
    }
  }
}
</style>
