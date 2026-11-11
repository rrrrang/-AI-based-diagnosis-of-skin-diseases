pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
        timeout(time: 15, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    environment {
        UI_NODE_DIR = 'D:/SkinAI_DevOps/tools/node-v24.22.2-win-x64'
        NPM_CONFIG_CACHE = 'D:/SkinAI_DevOps/npm-cache'
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
                    // Jenkins 작업용 복사본을 정리하고 다시 받습니다.
                    deleteDir()
                    checkout scm
                }
            }
        }

        stage('2. 필요한 패키지 설치') {
            steps {
                dir('source/frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
set "PATH=%UI_NODE_DIR%;%PATH%"
call "%UI_NODE_DIR%/npm.cmd" ci --include=dev
exit /b %ERRORLEVEL%
'''
                }
            }
        }

        stage('3. UI 빌드') {
            steps {
                dir('source/frontend') {
                    bat encoding: 'UTF-8', script: '''
@echo off
set "PATH=%UI_NODE_DIR%;%PATH%"
call "%UI_NODE_DIR%/npm.cmd" run build
exit /b %ERRORLEVEL%
'''
                }
            }
        }

        stage('4. 빌드 결과 보관') {
            steps {
                dir('source/frontend') {
                    script {
                        if (!fileExists('dist/index.html')) {
                            error('UI 빌드 결과인 dist/index.html이 없습니다.')
                        }
                    }

                    archiveArtifacts(
                        artifacts: 'dist/**',
                        fingerprint: true,
                        onlyIfSuccessful: true
                    )

                    echo 'UI 빌드 성공: 결과 파일을 Jenkins에 보관했습니다.'
                }
            }
        }
    }
}