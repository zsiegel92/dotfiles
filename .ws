
watchStatus(){
  watch --color -n 1 git -c color.status=always --no-optional-locks status
}
ws(){
  watchStatus
}


wd(){
  watch --color -n 1 git -c color.diff=always --no-pager diff
}