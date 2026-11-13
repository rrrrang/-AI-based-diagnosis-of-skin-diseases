pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    environment {
        UI_NODE_DIR = 'D:/SkinAI_DevOps/tools/node-v24.22.2-win-x64'
        NPM_CONFIG_CACHE = 'D:/SkinAI_DevOps/npm-cache'
        PLAYWRIGHT_BROWSERS_PATH = 'D:/SkinAI_DevOps/playwright-browsers'
        CI = 'true'
    }

    stages {
        stage('1. Git 코드 가져오기') {
            steps {
                script {
                    if (isUnix()) {
                        error('이 Jenkinsfile은 Windows 실행 환경용입니다.')
                    }
                }

                dir('source') {
                    // Jenkins 작업용 복사본만 정리합니다.
                    deleteDir()
                    checkout scm
                }
            }
        }

        stage('2. 환자 UI 패키지 설치') {
            steps {
                dir('source/frontend/patient-frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
set "PATH=%UI_NODE_DIR%;%PATH%"
call "%UI_NODE_DIR%/npm.cmd" ci --include=dev
exit /b %ERRORLEVEL%
'''
                }
            }
        }

        stage('3. 환자 UI 빌드') {
            steps {
                dir('source/frontend/patient-frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
set "PATH=%UI_NODE_DIR%;%PATH%"
call "%UI_NODE_DIR%/npm.cmd" run build
exit /b %ERRORLEVEL%
'''
                }
            }
        }

        stage('4. 의사 UI 패키지 설치') {
            steps {
                dir('source/frontend/doctor-frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
set "PATH=%UI_NODE_DIR%;%PATH%"
call "%UI_NODE_DIR%/npm.cmd" ci --include=dev
exit /b %ERRORLEVEL%
'''
                }
            }
        }

        stage('5. 의사 UI 빌드') {
            steps {
                dir('source/frontend/doctor-frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
set "PATH=%UI_NODE_DIR%;%PATH%"
call "%UI_NODE_DIR%/npm.cmd" run build
exit /b %ERRORLEVEL%
'''
                }
            }
        }

        stage('6. 자동검사 브라우저 준비') {
            steps {
                dir('source/frontend/patient-frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
chcp 65001 >nul
set "PATH=%UI_NODE_DIR%;%PATH%"
call ".\\node_modules\\.bin\\playwright.cmd" install chromium
exit /b %ERRORLEVEL%
'''
                }
            }
        }

        stage('7. 환자 필수 입력 자동검사') {
            steps {
                dir('source/frontend/patient-frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
chcp 65001 >nul
set "PATH=%UI_NODE_DIR%;%PATH%"
call ".\\node_modules\\.bin\\playwright.cmd" test tests/e2e/patient-required-input.spec.ts
exit /b %ERRORLEVEL%
'''
                }
            }

            post {
                always {
                    // 검사에 실패해도 원인을 확인할 기록은 보관합니다.
                    dir('source/frontend/patient-frontend') {
                        archiveArtifacts(
                            artifacts: 'test-results/**',
                            allowEmptyArchive: true
                        )
                    }
                }
            }
        }

        stage('8. 검사 통과한 UI 결과 보관') {
            steps {
                dir('source/frontend') {
                    script {
                        if (!fileExists('patient-frontend/dist/index.html')) {
                            error('환자 UI의 빌드 결과가 없습니다.')
                        }

                        if (!fileExists('doctor-frontend/dist/index.html')) {
                            error('의사 UI의 빌드 결과가 없습니다.')
                        }
                    }

                    archiveArtifacts(
                        artifacts: 'patient-frontend/dist/**,doctor-frontend/dist/**',
                        fingerprint: true,
                        onlyIfSuccessful: true
                    )

                    echo '두 UI 빌드와 환자 입력 검사를 통과하여 결과를 보관했습니다.'
                }
            }
        }
    }
}